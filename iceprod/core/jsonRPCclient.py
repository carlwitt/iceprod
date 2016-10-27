"""
A simple jsonrpc client using pycurl for the http connection
"""
import logging
from threading import RLock

from iceprod.core.jsonUtil import json_encode,json_decode
from iceprod.core.util import PycURL


class Client(object):
    """Raw JSONRPC client object"""
    id = 0
    idlock = RLock()

    def __init__(self,timeout=60.0,address=None,**kwargs):
        if address is None:
            raise Exception('need a valid address')
        # establish pycurl connection
        self.__pycurl = PycURL()
        # save timeout
        self.__timeout = timeout
        # save address
        self.__address = address
        # save connection options
        self.__opts = kwargs

    def close(self):
        self.__pycurl = None

    @classmethod
    def newid(cls):
        cls.idlock.acquire()
        id = cls.id
        cls.id += 1
        cls.idlock.release()
        return id

    def request(self,methodname,kwargs):
        """Send request to RPC Server"""
        # check method name for bad characters
        if methodname[0] == '_':
            logging.warning('cannot use RPC for private methods')
            raise Exception('Cannot use RPC for private methods')

        def cb(data):
            if data:
                cb.data += data
        cb.data = ''

        # translate request to json
        body = json_encode({'jsonrpc':'2.0','method':methodname,'params':kwargs,'id':Client.newid()})

        # make request to server
        kwargs = {'postbody':body,'timeout':self.__timeout}
        if self.__opts:
            # convert from ssl.wrap_socket to curl notation
            if 'sslkey' in self.__opts:
                kwargs['sslkey'] = self.__opts['sslkey']
            if 'sslcert' in self.__opts:
                kwargs['sslcert'] = self.__opts['sslcert']
            if 'cacert' in self.__opts:
                kwargs['cacert'] = self.__opts['cacert']
            # add options for basic_auth username and password
            if 'username' in self.__opts:
                kwargs['username'] = self.__opts['username']
            if 'password' in self.__opts:
                kwargs['password'] = self.__opts['password']
        try:
            logging.info('RPC pycurl options: %r',kwargs)
            self.__pycurl.post(self.__address,cb,**kwargs)
        except Exception as e:
            logging.warn('error making jsonrpc request: %r',e)
            raise

        # translate response from json
        if not cb.data:
            return None
        try:
            data = json_decode(cb.data)
        except:
            logging.info('json data: %r',cb.data)
            raise

        if 'error' in data:
            try:
                raise Exception('Error %r: %r    %r'%data['error'])
            except:
                raise Exception('Error %r'%data['error'])
        if 'result' in data:
            return data['result']
        else:
            return None

class MetaJSONRPC(type):
    """Metaclass for JSONRPC.  Allows for static class usage."""
    __rpc = None
    __timeout = None
    __address = None
    __passkey = None

    @classmethod
    def start(cls,timeout=None,address=None,passkey=None,**kwargs):
        """Start the JSONRPC Client."""
        if timeout is not None:
            cls.__timeout = timeout
        if address is not None:
            cls.__address = address
        if passkey is not None:
            cls.__passkey = passkey
        cls.__rpc = Client(timeout=cls.__timeout,address=cls.__address,
                           **kwargs)

    @classmethod
    def stop(cls):
        """Stop the JSONRPC Client."""
        cls.__rpc.close()
        cls.__rpc = None

    @classmethod
    def restart(cls):
        """Restart the JSONRPC Client."""
        cls.stop()
        cls.start()

    def __getattr__(cls,name):
        if cls.__rpc is None:
            raise Exception('JSONRPC connection not started yet')
        class _Method(object):
            def __init__(self,rpc,passkey,name):
                self.__rpc = rpc
                self.__name = name
                self.__passkey = passkey
            def __getattr__(self,name):
                return _Method(self.__rpc,"%s.%s"%(self.__name,name))
            def __call__(self,*args,**kwargs):
                # add passkey to arguments
                if 'passkey' not in kwargs:
                    kwargs['passkey'] = self.__passkey
                # jsonrpc can only handle args or kwargs, not both
                # so turn args into kwargs
                if len(args) > 0 and 'args' not in kwargs:
                    kwargs['args'] = args
                #return getattr(self.__rpc,self.__name)(**kwargs)
                return self.__rpc.request(self.__name,kwargs)
        return _Method(cls.__rpc,cls.__passkey,name)

class JSONRPC(object):
    """
    JSONRPC client connection.

    Call JSON-RPC functions as regular function calls.

    JSON-RPC spec: http://www.jsonrpc.org/specification

    Example::

        JSONRPC.set_task_status(task_id,'waiting')
    """
    __metaclass__ = MetaJSONRPC
    def __getattr__(self,name):
        return getattr(JSONRPC,name)