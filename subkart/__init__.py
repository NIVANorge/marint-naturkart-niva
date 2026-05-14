import rasterio as rio

from subkart import features, labelling, plot, smooth, sources, utils, training

__all__ = ["features", "utils", "labelling", "sources", "plot", "smooth", "training"]

rio.Env(GS_NO_SIGN_REQUEST="YES").__enter__()
