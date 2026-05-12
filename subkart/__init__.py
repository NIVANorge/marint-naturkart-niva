import rasterio as rio

from subkart import features, labelling, plot, sources, utils, training

__all__ = ["features", "utils", "labelling", "sources", "plot", "training"]

rio.Env(GS_NO_SIGN_REQUEST="YES").__enter__()
