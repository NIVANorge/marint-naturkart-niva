import rasterio as rio

from mnk.substrat import evaluation, features, interpolate, labelling, plot, utils, training

__all__ = [
    "features",
    "interpolate",
    "utils",
    "labelling",
    "plot",
    "training",
    "evaluation",
]

rio.Env(GS_NO_SIGN_REQUEST="YES").__enter__()
