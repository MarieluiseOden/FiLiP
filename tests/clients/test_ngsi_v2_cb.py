"""
Tests for filip.cb.client
"""
import unittest
import logging
import time
import random
import json
import paho.mqtt.client as mqtt
from datetime import datetime
from requests import RequestException
from filip.models.base import FiwareHeader, DataType
from filip.utils.simple_ql import QueryString
from filip.clients.ngsi_v2 import ContextBrokerClient, IoTAClient
from urllib.parse import urlparse
from filip.clients.ngsi_v2 import HttpClient, HttpClientConfig
from filip.config import settings
from filip.models.ngsi_v2.context import \
    AttrsFormat, \
    ContextEntity, \
    ContextAttribute, \
    NamedContextAttribute, \
    NamedCommand, \
    Subscription, \
    Query, \
    Entity, \
    ActionType
from filip.models.ngsi_v2.iot import \
    Device, \
    DeviceCommand, \
    DeviceAttribute, \
    ServiceGroup, \
    StaticDeviceAttribute

# Setting up logging
logging.basicConfig(
    level='ERROR',
    format='%(asctime)s %(name)s %(levelname)s: %(message)s')


class TestContextBroker(unittest.TestCase):
    """
    Test class for ContextBrokerClient
    """
    def setUp(self) -> None:
        """
        Setup test data
        Returns:
            None
        """
        self.resources = {
            "entities_url": "/v2/entities",
            "types_url": "/v2/types",
            "subscriptions_url": "/v2/subscriptions",
            "registrations_url": "/v2/registrations"
        }
        self.attr = {'temperature': {'value': 20.0,
                                     'type': 'Number'}}
        self.entity = ContextEntity(id='MyId', type='MyType', **self.attr)
        self.fiware_header = FiwareHeader(service='filip',
                                          service_path='/testing')

        self.client = ContextBrokerClient(fiware_header=self.fiware_header)


    def test_management_endpoints(self):
        """
        Test management functions of context broker client
        """
        with ContextBrokerClient(fiware_header=self.fiware_header) as client:
            self.assertIsNotNone(client.get_version())
            self.assertEqual(client.get_resources(), self.resources)

    def test_statistics(self):
        """
        Test statistics of context broker client
        """
        with ContextBrokerClient(fiware_header=self.fiware_header) as client:
            self.assertIsNotNone(client.get_statistics())

    def test_pagination(self):
        """
        Test pagination of context broker client
        Test pagination. only works if enough entities are available
        """
        fiware_header = FiwareHeader(service='filip',
                                     service_path='/testing')
        with ContextBrokerClient(fiware_header=fiware_header) as client:
            entities_a = [ContextEntity(id=str(i),
                                        type=f'filip:object:TypeA') for i in
                          range(0, 1000)]
            client.update(action_type=ActionType.APPEND, entities=entities_a)
            entities_b = [ContextEntity(id=str(i),
                                        type=f'filip:object:TypeB') for i in
                          range(1000, 2001)]
            client.update(action_type=ActionType.APPEND, entities=entities_b)
            self.assertLessEqual(len(client.get_entity_list(limit=1)), 1)
            self.assertLessEqual(len(client.get_entity_list(limit=999)), 999)
            self.assertLessEqual(len(client.get_entity_list(limit=1001)), 1001)
            self.assertLessEqual(len(client.get_entity_list(limit=2001)), 2001)

            client.update(action_type=ActionType.DELETE, entities=entities_a)
            client.update(action_type=ActionType.DELETE, entities=entities_b)

    def test_entity_filtering(self):
        """
        Test filter operations of context broker client
        """

        with ContextBrokerClient(fiware_header=self.fiware_header) as client:
            print(client.session.headers)
            # test patterns
            with self.assertRaises(ValueError):
                client.get_entity_list(id_pattern='(&()?')
            with self.assertRaises(ValueError):
                client.get_entity_list(type_pattern='(&()?')
            entities_a = [ContextEntity(id=str(i),
                                        type=f'filip:object:TypeA') for i in
                          range(0, 5)]

            client.update(action_type=ActionType.APPEND, entities=entities_a)
            entities_b = [ContextEntity(id=str(i),
                                        type=f'filip:object:TypeB') for i in
                          range(6, 10)]

            client.update(action_type=ActionType.APPEND, entities=entities_b)

            entities_all = client.get_entity_list()
            entities_by_id_pattern = client.get_entity_list(
                id_pattern='.*[1-5]')
            self.assertLess(len(entities_by_id_pattern), len(entities_all))

            entities_by_type_pattern = client.get_entity_list(
                type_pattern=".*TypeA$")
            self.assertLess(len(entities_by_type_pattern), len(entities_all))

            qs = QueryString(qs=[('presentValue', '>', 0)])
            entities_by_query = client.get_entity_list(q=qs)
            self.assertLess(len(entities_by_query), len(entities_all))

            # test options
            for opt in list(AttrsFormat):
                entities_by_option = client.get_entity_list(response_format=opt)
                self.assertEqual(len(entities_by_option), len(entities_all))
                self.assertEqual(client.get_entity(
                    entity_id='0',
                    response_format=opt),
                    entities_by_option[0])
            with self.assertRaises(ValueError):
                client.get_entity_list(response_format='not in AttrFormat')

            client.update(action_type=ActionType.DELETE, entities=entities_a)

            client.update(action_type=ActionType.DELETE, entities=entities_b)

    def test_entity_operations(self):
        """
        Test entity operations of context broker client
        """
        with ContextBrokerClient(fiware_header=self.fiware_header) as client:
            client.post_entity(entity=self.entity, update=True)
            res_entity = client.get_entity(entity_id=self.entity.id)
            client.get_entity(entity_id=self.entity.id, attrs=['temperature'])
            self.assertEqual(client.get_entity_attributes(
                entity_id=self.entity.id), res_entity.get_properties(
                response_format='dict'))
            res_entity.temperature.value = 25
            client.update_entity(entity=res_entity)
            self.assertEqual(client.get_entity(entity_id=self.entity.id),
                             res_entity)
            res_entity.add_properties({'pressure': ContextAttribute(
                type='Number', value=1050)})
            client.update_entity(entity=res_entity)
            self.assertEqual(client.get_entity(entity_id=self.entity.id),
                             res_entity)

    def test_attribute_operations(self):
        """
        Test attribute operations of context broker client
        """
        with ContextBrokerClient(fiware_header=self.fiware_header) as client:
            entity = self.entity
            attr_txt = NamedContextAttribute(name='attr_txt',
                                             type='Text',
                                             value="Test")
            attr_bool = NamedContextAttribute(name='attr_bool',
                                              type='Boolean',
                                              value=True)
            attr_float = NamedContextAttribute(name='attr_float',
                                               type='Number',
                                               value=round(random.random(), 5))
            attr_list = NamedContextAttribute(name='attr_list',
                                              type='StructuredValue',
                                              value=[1, 2, 3])
            attr_dict = NamedContextAttribute(name='attr_dict',
                                              type='StructuredValue',
                                              value={'key': 'value'})
            entity.add_properties([attr_txt,
                                   attr_bool,
                                   attr_float,
                                   attr_list,
                                   attr_dict])

            self.assertIsNotNone(client.post_entity(entity=entity,
                                                    update=True))
            res_entity = client.get_entity(entity_id=entity.id)

            for attr in entity.get_properties():
                self.assertIn(attr, res_entity.get_properties())
                res_attr = client.get_attribute(entity_id=entity.id,
                                                attr_name=attr.name)

                self.assertEqual(type(res_attr.value), type(attr.value))
                self.assertEqual(res_attr.value, attr.value)
                value = client.get_attribute_value(entity_id=entity.id,
                                                   attr_name=attr.name)
                # unfortunately FIWARE returns an int for 20.0 although float
                # is expected
                if isinstance(value, int) and not isinstance(value, bool):
                    value = float(value)
                self.assertEqual(type(value), type(attr.value))
                self.assertEqual(value, attr.value)

            for attr_name, attr in entity.get_properties(
                    response_format='dict').items():

                client.update_entity_attribute(entity_id=entity.id,
                                               attr_name=attr_name,
                                               attr=attr)
                value = client.get_attribute_value(entity_id=entity.id,
                                                   attr_name=attr_name)
                # unfortunately FIWARE returns an int for 20.0 although float
                # is expected
                if isinstance(value, int) and not isinstance(value, bool):
                    value = float(value)
                self.assertEqual(type(value), type(attr.value))
                self.assertEqual(value, attr.value)

            new_value = 1337.0
            client.update_attribute_value(entity_id=entity.id,
                                          attr_name='temperature',
                                          value=new_value)
            attr_value = client.get_attribute_value(entity_id=entity.id,
                                                    attr_name='temperature')
            self.assertEqual(attr_value, new_value)

            client.delete_entity(entity_id=entity.id)

    def test_type_operations(self):
        """
        Test type operations of context broker client
        """
        with ContextBrokerClient(fiware_header=self.fiware_header) as client:
            self.assertIsNotNone(client.post_entity(entity=self.entity,
                                                    update=True))
            client.get_entity_types()
            client.get_entity_types(options='count')
            client.get_entity_types(options='values')
            client.get_entity_type(entity_type='MyType')
            client.delete_entity(entity_id=self.entity.id)

    def test_subscriptions(self):
        """
        Test subscription operations of context broker client
        """
        with ContextBrokerClient(fiware_header=self.fiware_header) as client:
            sub_example = {
                "description": "One subscription to rule them all",
                "subject": {
                    "entities": [
                        {
                            "idPattern": ".*",
                            "type": "Room"
                        }
                    ],
                    "condition": {
                        "attrs": [
                            "temperature"
                        ],
                        "expression": {
                            "q": "temperature>40"
                        }
                    }
                },
                "notification": {
                    "http": {
                        "url": "http://localhost:1234"
                    },
                    "attrs": [
                        "temperature",
                        "humidity"
                    ]
                },
                "expires": datetime.now(),
                "throttling": 0
            }
            sub = Subscription(**sub_example)
            sub_id = client.post_subscription(subscription=sub)
            sub_res = client.get_subscription(subscription_id=sub_id)
            time.sleep(1)
            sub_update = sub_res.copy(update={'expires': datetime.now()})
            client.update_subscription(subscription=sub_update)
            sub_res_updated = client.get_subscription(subscription_id=sub_id)
            self.assertNotEqual(sub_res.expires, sub_res_updated.expires)
            self.assertEqual(sub_res.id, sub_res_updated.id)
            self.assertGreaterEqual(sub_res_updated.expires, sub_res.expires)

            # test duplicate prevention and update
            sub = Subscription(**sub_example)
            id1 = client.post_subscription(sub)
            sub_first_version = client.get_subscription(id1)
            sub.description = "This subscription shall not pass"

            id2 = client.post_subscription(sub, update=False)
            self.assertEqual(id1, id2)
            sub_second_version = client.get_subscription(id2)
            self.assertEqual(sub_first_version.description,
                             sub_second_version.description)

            id2 = client.post_subscription(sub, update=True)
            self.assertEqual(id1, id2)
            sub_second_version = client.get_subscription(id2)
            self.assertNotEqual(sub_first_version.description,
                                sub_second_version.description)

            # test that duplicate prevention does not prevent to much
            sub2 = Subscription(**sub_example)
            sub2.description = "Take this subscription to Fiware"
            sub2.subject.entities[0] = {
                            "idPattern": ".*",
                            "type": "Building"
                        }
            id3 = client.post_subscription(sub2)
            self.assertNotEqual(id1, id3)

            # Clean up
            subs = client.get_subscription_list()
            for sub in subs:
                client.delete_subscription(subscription_id=sub.id)

    def test_batch_operations(self):
        """
        Test batch operations of context broker client
        """
        fiware_header = FiwareHeader(service='filip',
                                     service_path='/testing')
        with ContextBrokerClient(fiware_header=fiware_header) as client:
            entities = [ContextEntity(id=str(i),
                                      type=f'filip:object:TypeA') for i in
                        range(0, 1000)]
            client.update(entities=entities, action_type=ActionType.APPEND)
            entities = [ContextEntity(id=str(i),
                                      type=f'filip:object:TypeB') for i in
                        range(0, 1000)]
            client.update(entities=entities, action_type=ActionType.APPEND)
            e = Entity(idPattern=".*", typePattern=".*TypeA$")
            q = Query.parse_obj({"entities": [e.dict(exclude_unset=True)]})
            self.assertEqual(1000,
                             len(client.query(query=q,
                                              response_format='keyValues')))


    def test_command_with_mqtt(self):
        """
        Test if a command can be send to a device in FIWARE

        To test this a virtual device is created and provisioned to FIWARE and
        a hosted MQTT Broker

        This test only works if the address of a running MQTT Broker is given in
        the environment ('MQTT_BROKER_URL')

        The main part of this test was taken out of the iot_mqtt_example, see
        there for a complete documentation
        """
        import os
        mqtt_broker_url = os.environ.get('MQTT_BROKER_URL')

        device_attr1 = DeviceAttribute(name='temperature',
                                       object_id='t',
                                       type="Number",
                                       metadata={"unit":
                                                     {"type": "Unit",
                                                      "value": {
                                                          "name": {
                                                              "type": "Text",
                                                              "value": "degree "
                                                                       "Celsius"
                                                          }
                                                      }}
                                                 })

        # creating a static attribute that holds additional information
        static_device_attr = StaticDeviceAttribute(name='info',
                                                   type="Text",
                                                   value="Filip example for "
                                                         "virtual IoT device")
        # creating a command that the IoT device will liston to
        device_command = DeviceCommand(name='heater', type="Boolean")

        device = Device(device_id='MyDevice',
                        entity_name='MyDevice',
                        entity_type='Thing2',
                        protocol='IoTA-JSON',
                        transport='MQTT',
                        apikey='filip-iot-test-device',
                        attributes=[device_attr1],
                        static_attributes=[static_device_attr],
                        commands=[device_command])

        device_attr2 = DeviceAttribute(name='humidity',
                                       object_id='h',
                                       type="Number",
                                       metadata={"unitText":
                                                     {"value": "percent",
                                                      "type": "Text"}})

        device.add_attribute(attribute=device_attr2)

        # Send device configuration to FIWARE via the IoT-Agent. We use the
        # general ngsiv2 httpClient for this.
        service_group = ServiceGroup(service=self.fiware_header.service,
                                     subservice=self.fiware_header.service_path,
                                     apikey='filip-iot-test-service-group',
                                     resource='/iot/json')

        # create the Http client node that once sent the device cannot be posted
        # again and you need to use the update command
        config = HttpClientConfig(cb_url=settings.CB_URL,
                                  iota_url=settings.IOTA_URL)
        client = HttpClient(fiware_header=self.fiware_header, config=config)
        client.iota.post_group(service_group=service_group, update=True)
        client.iota.post_device(device=device, update=True)

        time.sleep(0.5)

        # check if the device is correctly configured. You will notice that
        # unfortunately the iot API does not return all the metadata. However,
        # it will still appear in the context-entity
        device = client.iota.get_device(device_id=device.device_id)

        # check if the data entity is created in the context broker
        entity = client.cb.get_entity(entity_id=device.device_id,
                                      entity_type=device.entity_type)


        # create a mqtt client that we use as representation of an IoT device
        # following the official documentation of Paho-MQTT.
        # https://www.eclipse.org/paho/index.php?page=clients/python/
        # docs/index.php

        # The callback for when the mqtt client receives a CONNACK response from
        # the server. All callbacks need to have this specific arguments,
        # Otherwise the client will not be able to execute them.
        def on_connect(client, userdata, flags, reasonCode, properties=None):
            client.subscribe(f"/{device.apikey}/{device.device_id}/cmd")

        # Callback when the command topic is succesfully subscribed
        def on_subscribe(client, userdata, mid, granted_qos, properties=None):
            pass

        # NOTE: We need to use the apikey of the service-group to send the
        # message to the platform
        def on_message(client, userdata, msg):
            data = json.loads(msg.payload)
            res = {k: v for k, v in data.items()}
            client.publish(topic=f"/json/{service_group.apikey}"
                                 f"/{device.device_id}/cmdexe",
                           payload=json.dumps(res))

        def on_disconnect(client, userdata, reasonCode):
            pass

        mqtt_client = mqtt.Client(client_id="filip-iot-example",
                                  userdata=None,
                                  protocol=mqtt.MQTTv5,
                                  transport="tcp")

        # add our callbacks to the client
        mqtt_client.on_connect = on_connect
        mqtt_client.on_subscribe = on_subscribe
        mqtt_client.on_message = on_message
        mqtt_client.on_disconnect = on_disconnect

        # extract the MQTT_BROKER_URL form the environment
        mqtt_url = urlparse(mqtt_broker_url)

        mqtt_client.connect(host=mqtt_url.hostname,
                            port=mqtt_url.port,
                            keepalive=60,
                            bind_address="",
                            bind_port=0,
                            clean_start=mqtt.MQTT_CLEAN_START_FIRST_ONLY,
                            properties=None)
        # create a non-blocking thread for mqtt communication
        mqtt_client.loop_start()

        for attr in device.attributes:
            mqtt_client.publish(
                topic=f"/json/{service_group.apikey}/{device.device_id}/attrs",
                payload=json.dumps({attr.object_id: random.randint(0, 9)}))

        time.sleep(1)
        entity = client.cb.get_entity(entity_id=device.device_id,
                                      entity_type=device.entity_type)

        # create and send a command via the context broker
        context_command = NamedCommand(name=device_command.name,
                                       value=False)
        client.cb.post_command(entity_id=entity.id,
                               entity_type=entity.type,
                               command=context_command)

        time.sleep(1)
        # check the entity the command attribute should now show OK
        entity = client.cb.get_entity(entity_id=device.device_id,
                                      entity_type=device.entity_type)

        # The main part of this test, for all this setup was done
        self.assertEqual(entity.heater_status.value, "OK")

        # close the mqtt listening thread
        mqtt_client.loop_stop()
        # disconnect the mqtt device
        mqtt_client.disconnect()

        # cleanup the server and delete everything
        client.iota.delete_device(device_id=device.device_id)
        client.iota.delete_group(resource=service_group.resource,
                                 apikey=service_group.apikey)
        client.cb.delete_entity(entity_id=entity.id, entity_type=entity.type)


    def tearDown(self) -> None:
        """
        Cleanup test server
        """
        try:
            entities = [ContextEntity(id=entity.id, type=entity.type) for
                        entity in self.client.get_entity_list()]
            self.client.update(entities=entities, action_type='delete')
        except RequestException:
            pass

        self.client.close()