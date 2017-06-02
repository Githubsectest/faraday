# Faraday Penetration Test IDE
# Copyright (C) 2016  Infobyte LLC (http://www.infobytesec.com/)
# See the file 'doc/LICENSE' for the license information

import os
import functools

import twisted.web
from twisted.web import proxy
from twisted.internet import ssl, reactor, error
from twisted.protocols.tls import TLSMemoryBIOFactory
from twisted.web.static import File
from twisted.web.wsgi import WSGIResource
from autobahn.twisted.websocket import (
    WebSocketServerFactory,
    listenWS
)
import server.config
from server.utils import logger
from server.app import app
from server.websocket_factories import (
    WorkspaceServerFactory,
    BroadcastServerProtocol
)


class HTTPProxyClient(proxy.ProxyClient):
    def connectionLost(self, reason):
        if not reason.check(error.ConnectionClosed):
            logger.get_logger(__name__).error("Connection error: {}".format(reason.value))

        try:
            proxy.ProxyClient.connectionLost(self, reason)

        except RuntimeError, e:
            # Dirty way to ignore this expected exception from twisted. It happens
            # when one endpoint of the connection is still transmitting data while
            # the other one is disconnected.
            ignore_error_msg = 'Request.finish called on a request after its connection was lost'
            if ignore_error_msg not in e.message:
                raise e


class HTTPProxyClientFactory(proxy.ProxyClientFactory):
    protocol=HTTPProxyClient


class HTTPProxyResource(proxy.ReverseProxyResource):
    def __init__(self, host, port, path='', reactor=reactor, ssl_enabled=False):
        proxy.ReverseProxyResource.__init__(self, host, port, path, reactor)
        self.__ssl_enabled = ssl_enabled

    def render(self, request):
        logger.get_logger(__name__).debug("-> CouchDB: {} {}".format(request.method, request.uri))
        return proxy.ReverseProxyResource.render(self, request)

    def proxyClientFactoryClass(self, *args, **kwargs):
        """
        Overwrites proxyClientFactoryClass to add a TLS wrapper to all
        connections generated by ReverseProxyResource protocol factory
        if enabled.
        """
        client_factory = HTTPProxyClientFactory(*args, **kwargs)

        if self.__ssl_enabled:
            with open(server.config.ssl.certificate) as cert_file:
                cert = ssl.Certificate.loadPEM(cert_file.read())

            # TLSMemoryBIOFactory is the wrapper that takes TLS options and
            # the wrapped factory to add TLS to connections
            return TLSMemoryBIOFactory(
                ssl.optionsForClientTLS(self.host.decode('ascii'), cert),
                isClient=True, wrappedFactory=client_factory)
        else:
            return client_factory

    def getChild(self, path, request):
        """
        Keeps the implementation of this class throughout the path
        hierarchy
        """
        child = proxy.ReverseProxyResource.getChild(self, path, request)
        return HTTPProxyResource(
            child.host, child.port, child.path, child.reactor,
            ssl_enabled=self.__ssl_enabled)


class WebServer(object):
    UI_URL_PATH = '_ui'
    API_URL_PATH = '_api'
    WEB_UI_LOCAL_PATH = os.path.join(server.config.FARADAY_BASE, 'server/www')

    def __init__(self, enable_ssl=False):
        self.__ssl_enabled = enable_ssl
        self.__config_server()
        self.__config_couchdb_conn()
        self.__build_server_tree()

    def __config_server(self):
        self.__bind_address = server.config.faraday_server.bind_address
        self.__listen_port = int(server.config.faraday_server.port)
        if self.__ssl_enabled:
            self.__listen_port = int(server.config.ssl.port)

    def __config_couchdb_conn(self):
        """
        CouchDB connection setup for proxying
        """
        self.__couchdb_host = server.config.couchdb.host

        if self.__ssl_enabled:
            self.__couchdb_port = int(server.config.couchdb.ssl_port)
            ssl_context = self.__load_ssl_certs()
            self.__listen_func = functools.partial(reactor.listenSSL,
                                                   contextFactory=ssl_context)
        else:
            self.__couchdb_port = int(server.config.couchdb.port)
            self.__listen_func = reactor.listenTCP

    def __load_ssl_certs(self):
        certs = (server.config.ssl.keyfile, server.config.ssl.certificate)
        if not all(certs):
            logger.get_logger(__name__).critical("HTTPS request but SSL certificates are not configured")
            exit(1) # Abort web-server startup
        return ssl.DefaultOpenSSLContextFactory(*certs)

    def __build_server_tree(self):
        self.__root_resource = self.__build_proxy_resource()
        self.__root_resource.putChild(
            WebServer.UI_URL_PATH, self.__build_web_resource())
        self.__root_resource.putChild(
            WebServer.API_URL_PATH, self.__build_api_resource())

    def __build_proxy_resource(self):
        return HTTPProxyResource(
            self.__couchdb_host,
            self.__couchdb_port,
            ssl_enabled=self.__ssl_enabled)

    def __build_web_resource(self):
        return File(WebServer.WEB_UI_LOCAL_PATH)

    def __build_api_resource(self):
        return WSGIResource(reactor, reactor.getThreadPool(), app)

    def __build_websockets_resource(self):
        print(u"wss://{0}:9000".format(self.__bind_address))
        factory = WorkspaceServerFactory(u"ws://{0}:9000".format(self.__bind_address))
        factory.protocol = BroadcastServerProtocol
        return factory

    def run(self):
        site = twisted.web.server.Site(self.__root_resource)
        self.__listen_func(
            self.__listen_port, site,
            interface=self.__bind_address)
        listenWS(self.__build_websockets_resource())
        reactor.run()
