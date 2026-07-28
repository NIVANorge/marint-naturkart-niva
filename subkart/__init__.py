import rasterio as rio

from subkart import evaluation, features, interpolate, labelling, light, plot, sources, utils, training, vectorize

__all__ = [
    "features",
    "light",
    "interpolate",
    "utils",
    "labelling",
    "sources",
    "plot",
    "training",
    "vectorize",
    "evaluation",
]

rio.Env(GS_NO_SIGN_REQUEST="YES").__enter__()
