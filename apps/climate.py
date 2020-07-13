import appdaemon.plugins.mqtt.mqttapi as mqtt
import datetime
import json
import socket
import xml.etree.ElementTree

class Climate(mqtt.Mqtt):

    _debug = True

    _remote_address = '192.168.10.10'
    _local_address = '192.168.10.8'
    _remote_port = 10002
    _udp_discovery_port = 10001

    _server_socket = None
    _server_socket_conn = None
    _client_socket = None

    _discovery = '<myclimate><get>discovery</get><ip>{}</ip><platform>android</platform><version>1.0.0</version></myclimate>'.format(_local_address)
    _delete = '<myclimate><delete>connection</delete></myclimate>'
    _getzoneinfo = '<myclimate><get>getzoneinfo</get><zoneList>1,2</zoneList></myclimate>'

    _queued_commands = {'system': None,
                        'type': None,
                        'zoneList': None,
                        'mode': None,
                        'setPoint': None,}

    _states = {'system': None,
               'type': None,
               'zoneList': None,
               'mode': None,
               'setPoint': None,
               'roomTemp': None,}

    _time_of_last_command = None

    _connected = False


    def initialize(self):

        self.set_namespace('mqtt')

        # Setup the listener
        if(self._debug): self.log('Listening on TCP 10003.')
        self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_socket.bind(('', 10003))
        self._server_socket.listen(1)
        self._server_socket.settimeout(7)

        self.mqtt_publish('homeassistant/sensor/climate_status/config',
                          '{"name": "climate_status", '
                          '"state_topic": "homeassistant/sensor/climate_status/state"}', retain = True)

        self.mqtt_publish('homeassistant/sensor/climate_status/state', 'Disconnected', retain = True)

        self.run_every(self.start, datetime.datetime.now() + datetime.timedelta(seconds=10), 210)
        self.run_every(self.client_send, datetime.datetime.now() + datetime.timedelta(seconds=10), 2)
        self.listen_event(self.command_simple, 'MQTT_MESSAGE', topic = 'climate/command/zoneList')
        self.listen_event(self.command_simple, 'MQTT_MESSAGE', topic = 'climate/command/setPoint')
        self.listen_event(self.command_simple, 'MQTT_MESSAGE', topic = 'climate/command/mode')
        self.listen_event(self.command_type, 'MQTT_MESSAGE', topic = 'climate/command/type')


    # Start the whole process.
    def start(self, kwargs):

        # Set connected to false to prevent commands from being sent while not connected
        self._connected = False

        # Record the start time so that we can schedule a disconnect to minimise the gap between sessions
        start_time = datetime.datetime.now()

        # Run the discovery process, if this fails abort
        if not self.discovery(): return

        # Run the connect process, if this fails abort
        if not self.connect(): return

        # Do not run get_zone_info if there is a pending command
        if self._time_of_last_command is None:

            # Run get_zone_info to make sure we have up to date information from HVAC
            if not self.get_zone_info(): return

        # Set connect to true to allow pending commands to now be sent
        self._connected = True

        # Schedule in a disconnect to avoid the remote device ending the connection
        connect_duration = (datetime.datetime.now() - start_time).seconds
        self.run_in(self.disconnect, 205 - connect_duration)


    # Send a UDP discovery broadcast, wait 7 seconds for a connection. If
    # there is no connection after 10 seconds, send another UDP broadcast.
    # If there is a connection, then continue. Abort after three attempts.
    def discovery(self):

        # Attempt to discover the remote device up to three times
        attempts = 0

        while attempts < 3:

            attempts += 1

            if self._debug and attempts > 1: self.log('Discovery attempt #' + str(attempts))
            self.mqtt_publish('homeassistant/sensor/climate_status/state', 'Connecting' + attempts * '.', retain = True)

            try:
                # Create the UDP broadcast socket
                udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

                # Send the UDP discovery packet and close the UDP socket
                udp_sock.sendto(self._discovery.encode(), ('255.255.255.255', self._udp_discovery_port))
                udp_sock.close()

                # Wait for a connection request for 7 seconds
                self._server_socket_conn, addr = self._server_socket.accept()

            except socket.timeout as ex:
                if self._debug and attempts > 1: self.log('Timed out waiting for discovery response')

            else:
                # New connection on listener, continue to next step
                if(self._debug): self.log('New connection from: ' + addr[0] + ":" + str(addr[1]))
                return True

        # Discovery has failed, return false
        if(self._debug): self.log('Discovery failed, aborting')
        self.mqtt_publish('homeassistant/sensor/climate_status/state', 'Disconnected', retain = True)
        self._connected = False
        return False


    def connect(self):

        # Attempt to connect to the remote device up to three times
        attempts = 0

        while attempts < 3:

            attempts += 1

            if self._debug and attempts > 1: self.log('Connection attempt #' + str(attempts))
            self.mqtt_publish('homeassistant/sensor/climate_status/state', 'Connecting' + (attempts +3) * '.', retain = True)

            try:
                # Create the client socket
                self._client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self._client_socket.settimeout(5)

                self._client_socket.connect((self._remote_address, self._remote_port))

            except OSError as ex:
                if(self._debug): self.log(ex)

            else:
                if(self._debug): self.log('Connected to remote device')
                return True

        # Connect has failed, return false
        if(self._debug): self.log('Connect failed, aborting')
        self.mqtt_publish('homeassistant/sensor/climate_status/state', 'Disconnected', retain = True)
        self._connected = False
        return False


    def get_zone_info(self):

        # Attempt to get zone info from the remote device up to three times
        attempts = 0

        while attempts < 3:

            attempts += 1

            if self._debug and attempts > 1: self.log('Receiving Data #' + str(attempts))
            self.mqtt_publish('homeassistant/sensor/climate_status/state', 'Receiving Data' + (attempts) * '.', retain = True)

            data = None

            try:
                # Send the getzoneinfo request
                self._client_socket.send(self._getzoneinfo.encode())

                data = self._client_socket.recv(512)

            except socket.timeout as ex:
                pass

            except OSError as ex:
                if self._debug: self.log(ex)

            # If data is received, check that it is a zoneinfo and publish to MQTT
            if data:

                data = data.decode()
                if self._debug: self.log(data)

                root = xml.etree.ElementTree.fromstring(data)

                if self._debug: self.log('Data received, publishing to MQTT')
                self.mqtt_publish('homeassistant/sensor/climate_status/state', 'Connected', retain = True)
                self.publish_zoneinfo(root)
                return True

            else:
                if self._debug: self.log('get_zone_info: Not data')


        # Connect has failed, return false
        if(self._debug): self.log('Connect failed, aborting')
        self.mqtt_publish('homeassistant/sensor/climate_status/state', 'Disconnected', retain = True)
        self._connected = False
        self.run_in(self.disconnect, 1)
        return False


    def client_send(self, kwargs):

        if self._time_of_last_command is not None and self._connected == True and (datetime.datetime.now() - self._time_of_last_command).seconds > 5:

            if self._debug: self.log('Building command')
            self.mqtt_publish('homeassistant/sensor/climate_status/state', 'Sending Command', retain = True)

            # Start building the payload
            payload = '<myclimate><post>postzoneinfo</post>'

            # Loop through the queued commands
            for command, value in self._queued_commands.items():

                # If there is a queued command, add it to payload
                if value is not None:
                    payload += '<{0}>{1}</{0}>'.format(command, value)

                # Otherwise build out the payload with the current state
                else:
                    payload += '<{}>{}</{}>'.format(command, self._states[command], command)

            # Close out the payload
            payload += '</myclimate>'

            if self._debug: self.log('Will post command')
            if self._debug: self.log(payload)

            # Clear timer so that this will not run until more commands are received
            self._time_of_last_command = None

            # Clear all the queued commands, even if it was unsuccessful
            for command in self._queued_commands:
                self._queued_commands[command] = None

            self.run_in(self.post_zone_info, 1, payload = payload)


    # This will take a command payload and attempt to send it to the remote
    # device three times. It will wait for an acknowledgement packet before
    # continuing. If it fails after a third time, it will force an early
    # disconnect. 
    def post_zone_info(self, kwargs):

        payload = kwargs['payload']

        # Attempt to get zone info from the remote device up to three times
        attempts = 0

        while attempts < 3:

            attempts += 1

            if self._debug: self.log('Post zone info #' + str(attempts))
            self.mqtt_publish('homeassistant/sensor/climate_status/state', 'Sending Command' + (attempts) * '.', retain = True)

            # Reset data variable
            data = None

            try:
                # Send the payload
                self._client_socket.send(payload.encode())

                # Wait to receive an acknowledgement. If no acknowledgement, try again
                data = self._client_socket.recv(512)

            except socket.timeout as ex:
                pass

            except OSError as ex:
                if(self._debug): self.log(ex)

            # If data is received, check that it is correct, and then retreive current state to verify
            if data:

                data = data.decode()
                if(self._debug): self.log(data)

                if data == '<myclimate><response>postzoneinfo</response><result>ok</result></myclimate>':
                    return self.get_zone_info()
                else:
                    return False

            else:
                if(self._debug): self.log('get_zone_info: Not data')


        # Connect has failed, return false
        if(self._debug): self.log('Post zone info, aborting')
        self.mqtt_publish('homeassistant/sensor/climate_status/state', 'Disconnected', retain = True)
        self.run_in(self.disconnect, 1)
        return False

                
    # This will take an XML zoneinfo, and pull out the attributes and publish
    # them to MQTT. This function is triggered by a response to a get_zone_info
    def publish_zoneinfo(self, root):

        # Make sure that the message is well formed with the 'system' attribute
        post = root.find('system')

        if post is not None:

            # Pull out the attributes
            system = root.find('system')
            type = root.find('type')
            zoneList = root.find('zoneList')
            mode = root.find('mode')
            roomTemp = root.find('roomTemp')

            # Update the stored states
            self._states['system'] = system.text
            self._states['type'] = type.text
            self._states['zoneList'] = zoneList.text
            self._states['mode'] = mode.text
            self._states['roomTemp'] = roomTemp.text

            if system.text == 'off':
                self.mqtt_publish('climate/state/type', 'off', retain = True)

                setPoint = root.find('setPoint')
                self._states['setPoint'] = setPoint.text
                self.mqtt_publish('climate/state/setPoint', setPoint.text, retain = True)

            elif mode.text == 'fan':
                self.mqtt_publish('climate/state/type', 'fan_only', retain = True)
                self.mqtt_publish('climate/state/mode', 'off', retain = True)

            else:
                self.mqtt_publish('climate/state/type', type.text, retain = True)
                self.mqtt_publish('climate/state/mode', mode.text, retain = True)

                setPoint = root.find('setPoint')
                self._states['setPoint'] = setPoint.text
                self.mqtt_publish('climate/state/setPoint', setPoint.text, retain = True)

            self.mqtt_publish('climate/state/zoneList', zoneList.text, retain = True)
            self.mqtt_publish('climate/state/roomTemp', roomTemp.text, retain = True)


    # This will close all open sockets. This function is scheduled to run after
    # a period of being connected to avoid the case where the remote device
    # ends the session.
    def disconnect(self, kwargs):

        if(self._debug): self.log('Sending delete request')

        try:
            self._client_socket.send(self._delete.encode())
            self._client_socket.shutdown(socket.SHUT_RDWR)
            self._client_socket.close()

        except OSError as ex:
            pass

        self.mqtt_publish('homeassistant/sensor/climate_status/state', 'Disconnected', retain = True)
        
        # Set connected to false to prevent posting commands while disconnected
        self._connected = False


    # This is triggered by HA front end publishing to the topic 'climate/command/type'
    def command_type(self, event_name, data, kwargs):

        # Extract the payload
        payload = data['payload']

        if self._debug: self.log(payload)

        # Record the current time. Won't post the commands until a period of no commands has been seen
        self._time_of_last_command = datetime.datetime.now()

        # Store the command in a dictionary for processing by client_send
        if payload == 'off':
            self._queued_commands['system'] = 'off'

        elif payload == 'cool':
            self._queued_commands['system'] = 'on'
            self._queued_commands['type'] = 'cool'
            self._queued_commands['mode'] = 'thermo'

        elif payload == 'fan_only':
            self._queued_commands['system'] = 'on'
            self._queued_commands['type'] = 'cool'
            self._queued_commands['mode'] = 'fan'

        else:
            self._queued_commands['system'] = 'on'
            self._queued_commands['type'] = 'heat'
            self._queued_commands['mode'] = 'thermo'

        # Publish the new value back to MQTT so that HA front end updates in a timely manner
        self.mqtt_publish('climate/state/type', payload, retain = True)

        # Publish the status of the HVAC to MQTT
        self.mqtt_publish('homeassistant/sensor/climate_status/state', 'Waiting For More Commands', retain = True)


    # This is triggered by HA front end publishing a command. This can handle setPoint, zoneList or mode.
    def command_simple(self, event_name, data, kwargs):

        # Extract the topic
        topic = data['topic'][16:]

        # Extract the payload (econ, thermo or boost)
        payload = data['payload']

        if self._debug: self.log(payload)

        # Record the current time. Won't post the commands until a period of no commands has been seen
        self._time_of_last_command = datetime.datetime.now()

        # Store the command in a dictionary for processing by client_send
        self._queued_commands[topic] = payload

        # Publish the new value back to MQTT so that HA front end updates in a timely manner
        self.mqtt_publish('climate/state/{}'.format(topic), payload, retain = True)

        # Publish the status of the HVAC to MQTT
        self.mqtt_publish('homeassistant/sensor/climate_status/state', 'Waiting For More Commands', retain = True)
