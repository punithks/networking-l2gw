# Copyright (c) 2015 OpenStack Foundation.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
import copy
import socket
import ssl
import time

from oslo.serialization import jsonutils
from oslo_log import log as logging
from oslo_utils import excutils

from neutron.i18n import _LE
from neutron.i18n import _LW

from networking_l2gw.services.l2gateway.common import constants as n_const

LOG = logging.getLogger(__name__)
OVSDB_UNREACHABLE_MSG = _LW('Unable to reach OVSDB server %s')
OVSDB_CONNECTED_MSG = 'Connected to OVSDB server %s'


class BaseConnection(object):
    """Connects to OVSDB server.

       Connects to an ovsdb server with/without SSL
       on a given host and TCP port.
    """
    def __init__(self, conf, gw_config):
        self.responses = []
        self.connected = False
        self.gw_config = gw_config
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if gw_config.use_ssl:
            ssl_sock = ssl.wrap_socket(
                self.socket,
                server_side=False,
                keyfile=gw_config.private_key,
                certfile=gw_config.certificate,
                cert_reqs=ssl.CERT_REQUIRED,
                ssl_version=ssl.PROTOCOL_TLSv1,
                ca_certs=gw_config.ca_cert)
            self.socket = ssl_sock

        retryCount = 0
        while True:
            try:
                self.socket.connect((str(gw_config.ovsdb_ip),
                                     int(gw_config.ovsdb_port)))
                break
            except (socket.error, socket.timeout):
                LOG.warning(OVSDB_UNREACHABLE_MSG, gw_config.ovsdb_ip)
                if retryCount == conf.max_connection_retries:
                    # Retried for max_connection_retries times.
                    # Give up and return so that it can be tried in
                    # the next periodic interval.
                    with excutils.save_and_reraise_exception(reraise=True):
                        LOG.exception(_LE("Socket error in connecting to "
                                          "the OVSDB server"))
                else:
                    time.sleep(1)
                    retryCount += 1

        # Successfully connected to the socket
        LOG.debug(OVSDB_CONNECTED_MSG, gw_config.ovsdb_ip)
        self.connected = True

    def send(self, message, callback=None):
        """Sends a message to the OVSDB server."""
        if callback:
            self.callbacks[message['id']] = callback
        retry_count = 0
        bytes_sent = 0
        while retry_count <= n_const.MAX_RETRIES:
            try:
                bytes_sent = self.socket.send(jsonutils.dumps(message))
                if bytes_sent:
                    return True
            except Exception as ex:
                LOG.exception(_LE("Exception [%s] occurred while sending "
                                  "message to the OVSDB server"), ex)
            retry_count += 1

        LOG.warning(_LW("Could not send message to the "
                        "OVSDB server."))
        self.disconnect()
        return False

    def disconnect(self):
        """disconnects the connection from the OVSDB server."""
        self.socket.close()
        self.connected = False

    def _response(self, operation_id):
        x_copy = None
        to_delete = None
        for x in self.responses:
            if x['id'] == operation_id:
                x_copy = copy.deepcopy(x)
                to_delete = x
                break
        if to_delete:
            self.responses.remove(to_delete)
        return x_copy