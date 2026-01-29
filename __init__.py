from .qgispublisher_plugin import GISPublisherPlugin

def classFactory(iface):
    return GISPublisherPlugin(iface)
