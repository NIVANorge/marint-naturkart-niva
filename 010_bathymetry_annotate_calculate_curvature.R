
#
# Packages ----
#

library(dplyr)
library(purrr)
library(ggplot2)
library(stars)
library(terra)
library(sf)

#
# Bathymetry (DEM) ----
#

bathymetry_file <- "c:/Data/Mapdata/DEM25/DEM25Norge_west_norway.tif"
bathymetry_orig <- read_stars(bathymetry_file)

# aggregate by 4x4 blocks
# bathymetry <- stars::st_downsample(bathymetry_orig, n = 3, FUN = mean)
bathymetry <- bathymetry_orig
rm(bathymetry_orig)

hist(bathymetry)

gg <- ggplot() +
  geom_stars(data = bathymetry, downsample = 20) +
  scale_fill_fermenter(na.value = "grey90") +
  # scale_fill_fermenter(na.value = "grey90", breaks = seq(-900,100,100)) +
  coord_equal()

gg
xlim <- c(-20E3, 30E3)
ylim <- c(6870E3, 6920E3)
gg +
  annotate("rect", xmin = xlim[1], xmax = xlim[2], ymin = ylim[1], ymax = ylim[2], 
           fill = NA, col = "red")
gg + 
  coord_equal(xlim = xlim, ylim = ylim)
xlim2 <- c(10E3, 30E3)
ylim2 <- c(6880E3, 6900E3)
gg + 
  coord_equal(xlim = xlim, ylim = ylim) +
  annotate("rect", xmin = xlim2[1], xmax = xlim2[2], ymin = ylim2[1], ymax = ylim2[2], 
           fill = NA, col = "red")



#
# Sediment data ----
#

fn <- list.files(
  "C:/Data/Mapdata/NGU_marine_sediment/Geologi_0000_Norge_25833_BunnsedimentKornstorDetalj_GML/", pattern = "gml$",
  full.names = TRUE)
fn
st_layers(fn)
sediment_polys <- st_read(fn, layer = "KornstrFlate")  

# slow
if (FALSE){
  ggplot() +
    geom_sf(data = sediment_polys)
}

# Ensure both are in the same CRS (WGS 84 / UTM zone 33N = EPSG:32633)
sediment_polys <- st_transform(sediment_polys, st_crs(bathymetry))


# Assuming you have a column 'sediment_class' with various classes
# Define which classes count as "sediment-covered"
sediment_classes <- c("mud", "sand", "gravel", "mixed_sediment")  # adjust to your classes

sed_soft <- c("Grusholdig sandholdig slam", "Leire", 
              "Sandholdig slam", "Slam", 
              "Slam og sand med grus, stein og blokk")
sediment_polys <- sediment_polys %>% 
  mutate(
    sediment_binary = ifelse(sedKornstørrelseNavn %in% sed_soft, 1, 0))
    

#
# . annotate bathymetry with sediment data ----
#
# rasterize sediment data
#

# Create a template raster from bathymetry with only the spatial structure
template <- bathymetry
template[[1]][] <- NA  # Clear values, keep structure

# Rasterize the sediment polygons using the bathymetry grid as template
sediment_raster <- st_rasterize(
  sediment_polys["sediment_binary"],  # Select only the binary classification
  template = template
)

# Alternative if st_rasterize has issues - use stars::st_as_stars
# sediment_raster <- st_as_stars(
#   sediment_polys["sediment_binary"],
#   dx = 25, dy = 25,  # your grid resolution
#   xlim = st_bbox(bathymetry)[c("xmin", "xmax")],
#   ylim = st_bbox(bathymetry)[c("ymin", "ymax")]
# )

#
# . calculate slope ----
#


# Define function to calculate slope at different window sizes
calculate_slope_multiscale <- function(dem, window_size = 3) {
  # Create distance weights based on window size
  half_win <- floor(window_size / 2)
  cell_size <- res(dem)[1]  # assuming square cells
  
  # Create focal weight matrices for derivatives
  # Sobel-like filters scaled to window size
  weights_x <- matrix(0, nrow = window_size, ncol = window_size)
  weights_y <- matrix(0, nrow = window_size, ncol = window_size)
  
  # Fill weights for x-direction (east-west)
  for(i in 1:window_size) {
    for(j in 1:window_size) {
      dist_x <- (j - (half_win + 1)) * cell_size
      dist_y <- (i - (half_win + 1)) * cell_size
      if(dist_x != 0) {
        weights_x[i, j] <- -dist_x / (dist_x^2 + dist_y^2 + 1e-10)
      }
    }
  }
  
  # Fill weights for y-direction (north-south)
  for(i in 1:window_size) {
    for(j in 1:window_size) {
      dist_x <- (j - (half_win + 1)) * cell_size
      dist_y <- (i - (half_win + 1)) * cell_size
      if(dist_y != 0) {
        weights_y[i, j] <- dist_y / (dist_x^2 + dist_y^2 + 1e-10)
      }
    }
  }
  
  # Normalize weights
  weights_x <- weights_x / sum(abs(weights_x))
  weights_y <- weights_y / sum(abs(weights_y))
  
  # Calculate derivatives
  dz_dx <- focal(dem, w = weights_x, fun = sum, na.rm = TRUE)
  dz_dy <- focal(dem, w = weights_y, fun = sum, na.rm = TRUE)
  
  # Calculate slope
  slope <- atan(sqrt(dz_dx^2 + dz_dy^2)) * 180 / pi
  
  return(slope)
}

# Convert stars to terra
bath_terra <- rast(bathymetry)

# Calculate slope at multiple scales
slope_3x3 <- calculate_slope_multiscale(bath_terra, window_size = 3)
# slope_5x5 <- calculate_slope_multiscale(bath_terra, window_size = 5)
slope_7x7 <- calculate_slope_multiscale(bath_terra, window_size = 7)
slope_11x11 <- calculate_slope_multiscale(bath_terra, window_size = 11)

#
# . calculate curvature ----
# Gaussian smoothing approach for curvature 
# Several scales  
#

# Function to calculate curvature with smoothing
calculate_curvature_multiscale <- function(dem, sigma = 1) {
  cell_size <- res(dem)[1]
  
  # Create Gaussian kernel
  window_size <- ceiling(sigma * 4) * 2 + 1  # 4 sigma coverage, odd number
  half_win <- floor(window_size / 2)
  
  # Create Gaussian weight matrix
  gauss_weights <- matrix(0, window_size, window_size)
  for(i in 1:window_size) {
    for(j in 1:window_size) {
      x <- (j - (half_win + 1))
      y <- (i - (half_win + 1))
      gauss_weights[i, j] <- exp(-(x^2 + y^2) / (2 * sigma^2))
    }
  }
  gauss_weights <- gauss_weights / sum(gauss_weights)
  
  # Smooth DEM
  dem_smooth <- focal(dem, w = gauss_weights, fun = sum, na.rm = TRUE)
  
  # Calculate second derivatives on smoothed DEM
  # Using centered differences for second derivatives
  
  # Second derivative matrices
  d2_dx2 <- matrix(c(0, 0, 0, 
                     1, -2, 1, 
                     0, 0, 0) / (cell_size^2), 3, 3)
  
  d2_dy2 <- matrix(c(0, 1, 0, 
                     0, -2, 0, 
                     0, 1, 0) / (cell_size^2), 3, 3)
  
  d2_dxy <- matrix(c(1, 0, -1, 
                     0, 0, 0, 
                     -1, 0, 1) / (4 * cell_size^2), 3, 3)
  
  # Calculate curvatures
  zxx <- focal(dem_smooth, w = d2_dx2, fun = sum, na.rm = TRUE)
  zyy <- focal(dem_smooth, w = d2_dy2, fun = sum, na.rm = TRUE)
  zxy <- focal(dem_smooth, w = d2_dxy, fun = sum, na.rm = TRUE)
  
  # Profile curvature (curvature in direction of slope)
  # Plan curvature (curvature perpendicular to slope)
  # Mean curvature
  mean_curvature <- (zxx + zyy) / 2
  
  # Gaussian curvature
  gaussian_curvature <- zxx * zyy - zxy^2
  
  return(list(
    profile = zxx,  # simplified - true profile needs slope direction
    plan = zyy,     # simplified - true plan needs slope direction
    mean = mean_curvature,
    gaussian = gaussian_curvature
  ))
}

help(package = "terra")

# Calculate curvature at different scales
t0 <- Sys.time()
curv_3x3 <- calculate_curvature_multiscale(bath_terra, sigma = 0.5)  # ~3x3
t1 <- Sys.time()
curv_5x5 <- calculate_curvature_multiscale(bath_terra, sigma = 1.0)  # ~5x5, ca. 40 sec.
t2 <- Sys.time()
curv_9x9 <- calculate_curvature_multiscale(bath_terra, sigma = 2.0)  # ~9x9, ca. 2.5 mins
t3 <- Sys.time()
curv_13x13 <- calculate_curvature_multiscale(bath_terra, sigma = 3.0)  # ~13x13, ca. 4 mins
t4 <- Sys.time()
cat("total time:")
t4-t0

# plot(curv_13x13$profile)
# plot(curv_13x13$plan)
# plot(curv_13x13$mean)
plot(curv_13x13$gaussian)  
hist(curv_13x13$gaussian*1000)

dim(bath_terra)
dim(curv_13x13$gaussian)



#
# . merge ----
# merge both rasters into a single dataset
#

# Method 1: Create a multi-band stars object
# combined_data <- c(bathymetry, sediment_raster, along = 3)
# names(combined_data) <- c("depth", "sediment_class")

# Method 2: Add as an attribute to the bathymetry stars object
# bathymetry$sediment_class <- sediment_raster[[1]]

# Method 3: Convert to data frame for ML preparation (useful for next steps)
# This creates a row for each pixel with coordinates and values
df_combined <- as.data.frame(bathymetry, xy = TRUE) %>%
  rename(depth = DEM25Norge_west_norway.tif) %>%  # rename the first value column
  mutate(
    sediment_class = as.vector(sediment_raster[[1]]),
    has_sediment_data = !is.na(sediment_class)
  )

df_combined$slope_3x3 <- as.vector(slope_3x3)
df_combined$slope_7x7 <- as.vector(slope_7x7)
df_combined$slope_11x11 <- as.vector(slope_11x11)
df_combined$curv_gau_3x3 <- as.vector(curv_3x3$gaussian)
df_combined$curv_gau_5x5 <- as.vector(curv_5x5$gaussian)
df_combined$curv_gau_9x9 <- as.vector(curv_9x9$gaussian)
df_combined$curv_gau_13x13 <- as.vector(curv_13x13$gaussian)


xtabs(~addNA(sediment_class) + has_sediment_data, df_combined)
table(df_combined$has_sediment_data)
#    FALSE     TRUE 
# 66852221  5659779



#
# Appendix 1 ----
#

# Evans-Wood polynomial method for larger windows
calculate_wood_curvature <- function(dem, window_size = 5) {
  cell_size <- res(dem)[1]
  half_win <- floor(window_size / 2)
  
  # Create a custom focal function that fits polynomial
  curvature_focal <- function(x) {
    if(sum(!is.na(x)) < 6) return(NA)  # Need at least 6 points
    
    # Create coordinate grid
    coords <- expand.grid(
      x = seq(-half_win, half_win) * cell_size,
      y = seq(-half_win, half_win) * cell_size
    )
    coords$z <- as.vector(x)
    coords <- coords[!is.na(coords$z), ]
    
    # Fit quadratic surface: z = ax^2 + by^2 + cxy + dx + ey + f
    if(nrow(coords) >= 6) {
      fit <- lm(z ~ I(x^2) + I(y^2) + I(x*y) + x + y, data = coords)
      coef <- coefficients(fit)
      
      # Curvature from polynomial coefficients
      # Mean curvature = (Zxx + Zyy) where Zxx = 2a, Zyy = 2b
      mean_curv <- 2 * (coef[2] + coef[3])
      return(mean_curv)
    } else {
      return(NA)
    }
  }
  
  # Apply to raster
  curvature <- focal(dem, w = matrix(1, window_size, window_size), 
                     fun = curvature_focal, expand = TRUE)
  
  return(curvature)
}

# Convert stars to terra if needed
bath_terra <- rast(bathymetry)

# Calculate Wood curvature at different scales
debugonce(calculate_wood_curvature)
wood_curv_5x5 <- calculate_wood_curvature(bath_terra, window_size = 5)
wood_curv_7x7 <- calculate_wood_curvature(bath_terra, window_size = 7)

#
# Appendix 2 - test curvature on 5x5 raster data ----
#

# . example 1 ----  

# Create a 5x5 raster with convex topography (dome/hill shape)
# Method 1: Simple parabolic dome
r <- rast(nrows = 5, ncols = 5, 
          xmin = 0, xmax = 5, 
          ymin = 0, ymax = 5,
          crs = "EPSG:32633")  # UTM 33N or use "+proj=longlat" for geographic

# Get cell coordinates
xy <- xyFromCell(r, 1:ncell(r))
x <- xy[,1]
y <- xy[,2]

# Calculate convex surface (parabolic dome)
# Centered at (2.5, 2.5) with peak height of 100
center_x <- 2.5
center_y <- 2.5
max_height <- 100
radius <- 3  # controls how steep the dome is

# Parabolic formula: height decreases with square of distance from center
distance <- sqrt((x - center_x)^2 + (y - center_y)^2)
elevation <- max_height * (1 - (distance/radius)^2)
elevation[elevation < 0] <- 0  # Clip negative values

# Assign values to raster
values(r) <- elevation

# Plot to visualize
plot(r, main = "Convex Topography (5x5)")
text(r)  # Add values to cells

# Print the values as matrix to see the dome shape
print(as.matrix(r, wide = TRUE))

curv_3x3 <- calculate_curvature_multiscale(r, sigma = 0.5)  # ~3x3
plot(curv_3x3$profile)
plot(curv_3x3$plan)
plot(curv_3x3$mean)
plot(curv_3x3$gaussian)

curv_5x5 <- calculate_curvature_multiscale(r, sigma = 1.0)  # ~5x5
plot(curv_5x5$profile)
plot(curv_5x5$plan)
plot(curv_5x5$mean)
plot(curv_5x5$gaussian)

# . example 2 ----  
r <- rast(nrows = 5, ncols = 5, 
          xmin = 0, xmax = 5, 
          ymin = 0, ymax = 5,
          crs = "EPSG:32633")  # UTM 33N or use "+proj=longlat" for geographic

# Get cell coordinates
xy <- xyFromCell(r, 1:ncell(r))
x <- xy[,1]
y <- xy[,2]

elevation <- ifelse(x >= 1.5 & x <= 3.5 & y >= 1.5 & y <= 3.5, 100, 0)
values(r) <- elevation

curv_3x3 <- calculate_curvature_multiscale(r, sigma = 0.5)  # ~3x3
plot(curv_3x3$profile)
plot(curv_3x3$plan)
plot(curv_3x3$mean)
plot(curv_3x3$gaussian)
persp(curv_3x3$gaussian, theta = 30, phi = 30, expand = 0.5, col = "lightblue")

curv_5x5 <- calculate_curvature_multiscale(r, sigma = 1.0)  # ~5x5
plot(curv_5x5$profile)
plot(curv_5x5$plan)
plot(curv_5x5$mean)
plot(curv_5x5$gaussian)
persp(curv_5x5$gaussian, theta = 30, phi = 30, expand = 0.5, col = "lightblue")


# Appendix 3 - test 'whitebox' package ----

# https://www.whiteboxgeo.com/
# https://www.whiteboxgeo.com/manual/wbt_book/intro.html

#
# . 
#


# install.packages("whitebox")
# whitebox::install_whitebox()
library(whitebox)
wbt_version()
wbt_exe_path(shell_quote = FALSE)

# sample DEM input GeoTIFF
input <- sample_dem_data()

# output file (to be created)
output <- file.path(tempdir(), "slope.tif")

bathymetry_slope <- "c:/Data/Mapdata/DEM25/DEM25Norge_west_norway_slope.tif"
wbt_slope(bathymetry_file, bathymetry_slope, units = 'radians')

bathymetry_curve_magnitude <- "c:/Data/Mapdata/DEM25/DEM25Norge_west_norway_curvmagn.tif"
bathymetry_curve_scale <- "c:/Data/Mapdata/DEM25/DEM25Norge_west_norway_curvscal.tif"

# WhiteboxTools has multiscale curvature options
?whitebox::wbt_multiscale_curvatures
whitebox::wbt_multiscale_curvatures(
  dem = bathymetry_file,
  out_mag = bathymetry_curve_magnitude,
  out_scale = bathymetry_curve_scale,
  min_scale = 1,
  num_steps = 3,
  step_nonlinearity = 1.5
)
# Error running WhiteboxTools (MultiscaleCurvatures)
# thread 'main' panicked at whitebox-tools-app\src\main.rs:72:21:
#   Unrecognized tool name MultiscaleCurvatures.


