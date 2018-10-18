# -*- coding: utf-8 -*-

import socket
import logging
import time
from paradox_crypto import encrypt, decrypt
from paradox_ip_messages import *
import binascii
import json
import stun
import requests

from config_defaults import *
from config import *

logger = logging.getLogger('PAI').getChild(__name__)

class IPConnection:
    def __init__(self, host='127.0.0.1', port=10000, password=IP_CONNECTION_PASSWORD, timeout=5):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.bind( ('0.0.0.0', 0))
        self.socket_timeout = int(timeout)
        self.key = password
        self.connected = False
        self.host = host
        self.port = port
        self.site_info = None

    def connect(self):

        tries = 1

        while tries > 0:
            try:
                if IP_CONNECTION_SITEID is not None and IP_CONNECTION_EMAIL is not None:
                    r = self.connect_to_site()
                     
                    if r and self.site_info is not None:
                        if self.connect_to_panel():
                            return True
                    
                else:
                    self.socket.settimeout(self.socket_timeout)
                    self.socket.connect( (self.host, self.port) )

                    if self.connect_to_panel():
                        return True
            except:
                logger.exception("Unable to connect")

            tries -= 1

        return False
    
    def connect_to_site(self):
        logger.info("Connecting to Site: {}".format(IP_CONNECTION_SITEID))
        if self.site_info is None:
            self.site_info = self.get_site_info(siteid=IP_CONNECTION_SITEID, email=IP_CONNECTION_EMAIL)
        
        if self.site_info is None:
            logger.error("Unable to get site info")
            return False
        try:
            logger.debug("Site Info: {}".format(json.dumps(self.site_info, indent=4)))
            chost = self.site_info['site'][0]['module'][0]['ipAddress']
            cport = self.site_info['site'][0]['module'][0]['port']
            xoraddr = binascii.unhexlify(self.site_info['site'][0]['module'][0]['xoraddr'])
            
            stun_host = 'turn.paradoxmyhome.com'

            self.client = stun.StunClient(stun_host)

            self.client.send_tcp_change_request()
            stun_r = self.client.receive_response()
            if stun.is_error(stun_r):
                logger.error(stun.get_error(stun_r))
                return False

            self.client.send_binding_request()
            stun_r = self.client.receive_response()
            if stun.is_error(stun_r):
                logger.error(stun.get_error(stun_r))
                return False

            self.client.send_connect_request(xoraddr=xoraddr)
            stun_r = self.client.receive_response()
            if stun.is_error(stun_r):
                logger.error(stun.get_error(stun_r))
                return False

            connection_id = stun_r[0]['attr_body']
            raddr = self.client.sock.getpeername()

            self.client1 = stun.StunClient(host=raddr[0], port=raddr[1])
            self.client1.send_connection_bind_request(binascii.unhexlify(connection_id))
            stun_r = self.client1.receive_response()
            if stun.is_error(stun_r):
                logger.error(stun.get_error(stun_r))
                return False

            self.socket = self.client1.sock
            logger.info("Connected to Site: {}".format(IP_CONNECTION_SITEID))
        except:
            logger.exception("Unable to negotiate connection to site")

        return True

    def connect_to_panel(self):

        logger.debug( "Connecting to IP Panel")
        
        try:    
            logger.debug("IP Connection established")

            payload = encrypt(self.key, self.key)

            msg = ip_message.build(dict(header=dict(length=len(self.key), unknown0=0x03, flags=0x09, command=0xf0, unknown1=0, encrypt=1), payload=payload))
            if LOGGING_DUMP_PACKETS:
                logger.debug("PC -> IP {}".format(binascii.hexlify(msg)))
            
            self.socket.send(msg)
            data = self.socket.recv(1024)
            if LOGGING_DUMP_PACKETS:
                logger.debug("IP -> PC {}".format(binascii.hexlify(data)))

            message, message_payload = self.get_message_payload(data)

            response = ip_payload_connect_response.parse(message_payload)
            self.key = response.key
            logger.info("Connected to Panel with version {}.{} - {}.{}".format(response.major, response.minor, response.ip_major, response.ip_minor))
            
            #F2
            msg = ip_message.build(dict(header=dict(length=0, unknown0=0x03, flags=0x09, command=0xf2, unknown1=0, encrypt=1), payload=encrypt(b'', self.key)))
            if LOGGING_DUMP_PACKETS:
                logger.debug("PC -> IP {}".format(binascii.hexlify(msg)))

            self.socket.send(msg)
            data = self.socket.recv(1024)
            if LOGGING_DUMP_PACKETS:
                logger.debug("IP -> PC {}".format(binascii.hexlify(data)))

            message, message_payload = self.get_message_payload(data)
            logger.debug("F2 answer: {}".format(binascii.hexlify(message_payload)))

            #F3
            msg = ip_message.build(dict(header=dict(length=0, unknown0=0x03, flags=0x09, command=0xf3, unknown1=0, encrypt=1), payload=encrypt(b'', self.key)))
            if LOGGING_DUMP_PACKETS:
                logger.debug("PC -> IP {}".format(binascii.hexlify(msg)))

            self.socket.send(msg)
            data = self.socket.recv(1024)
            if LOGGING_DUMP_PACKETS:
                logger.debug("IP -> PC {}".format(binascii.hexlify(data)))

            message, message_payload = self.get_message_payload(data)
            
            logger.debug("F3 answer: {}".format(binascii.hexlify(message_payload)))
           
            #F8
            payload = binascii.unhexlify('0a500080000000000000000000000000000000000000000000000000000000000000000000d0')
            payload_len = len(payload)
            payload = encrypt(payload, self.key)
            msg = ip_message.build(dict(header=dict(length=payload_len, unknown0=0x03, flags=0x09, command=0xf8, unknown1=0, encrypt=1), payload=payload))

            if LOGGING_DUMP_PACKETS:
                logger.debug("PC -> IP {}".format(binascii.hexlify(msg)))

            self.socket.send(msg)
            data = self.socket.recv(1024)
            if LOGGING_DUMP_PACKETS:
                logger.debug("IP -> PC {}".format(binascii.hexlify(data)))
            
            message, message_payload = self.get_message_payload(data)            
            logger.debug("F8 answer: {}".format(binascii.hexlify(message_payload)))
            
            
            logger.info("Connection fully established")

            self.connected = True
        except Exception as e:
            self.connected = False
            logger.exception("Unable to connect to IP Module")

        return self.connected

    def write(self, data):
        """Write data to socket"""

        try:
            if self.connected:
                payload = encrypt(data, self.key)
                msg = ip_message.build(dict(header=dict(length=len(data), unknown0=0x04, flags=0x09, command=0x00, encrypt=1), payload=payload))
                self.socket.send(msg)
                return True
            else:
                return False
        except:
            logger.exception("Error writing to socket")
            self.connected = False
            return False
        
    def read(self, sz=37, timeout=5):        
        """Read data from the IP Port, if available, until the timeout is exceeded"""
        self.socket.settimeout(timeout)
        data = b""
        read_sz = sz

        while True: 
            try:
                recv_data = self.socket.recv(1024)
            except:
                return None

            if recv_data is None or len(recv_data) == 0:
                continue

            data += recv_data
            
            if data[0] != 0xaa:
                data = b''
                continue

            if len(recv_data) + 16 < data[1]:
                continue

            if len(data) % 16 != 0:
                continue

            message, payload = self.get_message_payload(data)
            return payload
            
        return None
    
    def timeout(self, timeout=5):
        self.socket_timeout = timeout

    def close(self):
        """Closes the serial port"""
        if self.connected:
            self.connected = False
            self.socket.close()

    def flush(self):
        """Write any pending data"""
        self.socket.flush()

    def getfd(self):
        """Gets the FD associated with the socket"""
        if self.connected:
            return self.socket.fileno()

        return None

    def get_message_payload(self, data):
        message = ip_message.parse(data)
    

        if len(message.payload) >= 16 and len(message.payload) % 16 == 0 and message.header.flags & 0x01 != 0:
            message_payload = decrypt(data[16:], self.key)[:message.header.length]
        else:
            message_payload = message.payload

        return message, message_payload

    def get_site_info(self, email, siteid):

        logger.debug("Getting site info")
        URL = "https://api.insightgoldatpmh.com/v1/site"

        headers={'User-Agent': 'Mozilla/3.0 (compatible; Indy Library)', 'Accept-Encoding': 'identity', 'Accept': 'text/html, */*'}
        req = requests.get(URL, headers=headers, params = {'email': email, 'name': siteid})
        if req.status_code == 200:
            return req.json()

        return None




