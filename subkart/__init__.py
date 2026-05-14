import rasterio as rio

from subkart import features, labelling, plot, sources, utils, training, vectorize

__all__ = ["features", "utils", "labelling", "sources", "plot", "training", "vectorize"]

rio.Env(GS_NO_SIGN_REQUEST="YES").__enter__()
