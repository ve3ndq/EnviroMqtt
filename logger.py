import collections, threading, traceback

import paho.mqtt.client as mqtt

try:
    # Transitional fix for breaking change in LTR559
    from ltr559 import LTR559
    ltr559 = LTR559()
except ImportError:
    import ltr559

from bme280 import BME280
from pms5003 import PMS5003
from enviroplus import gas


class EnvLogger:
    def __init__(self, client_id, host, port, username, password, prefix, use_pms5003, num_samples):
        self.bme280 = BME280()

        self.prefix = prefix

        self.connection_error = None
        self.client = mqtt.Client(client_id=client_id)
        self.client.on_connect = self.__on_connect
        self.client.username_pw_set(username, password)
        self.client.connect(host, port)
        self.client.loop_start()

        self.samples = collections.deque(maxlen=num_samples)
        self.latest_pms_readings = {}

        if use_pms5003:
            self.pm_thread = threading.Thread(target=self.__read_pms_continuously)
            self.pm_thread.daemon = True
            self.pm_thread.start()
    

    def __on_connect(self, client, userdata, flags, rc):
        errors = {
            1: "incorrect MQTT protocol version",
            2: "invalid MQTT client identifier",
            3: "server unavailable",
            4: "bad username or password",
            5: "connection refused"
        }

        if rc > 0:
            self.connection_error = errors.get(rc, "unknown error")


    def __read_pms_continuously(self):
        """Continuously reads from the PMS5003 sensor and stores the most recent values
        in `self.latest_pms_readings` as they become available.

        If the sensor is not polled continously then readings are buffered on the PMS5003,
        and over time a significant delay is introduced between changes in PM levels and 
        the corresponding change in reported levels."""

        pms = PMS5003()
        while True:
            try:
                pm_data = pms.read()
                #print(pm_data)
                 
#                pm100 = pm_data.pm_per_1l_air(10.0)
#                pm50  = pm_data.pm_per_1l_air(5.0) - pm100
#                pm25  = pm_data.pm_per_1l_air(2.5) - pm100 - pm50
#                pm10  = pm_data.pm_per_1l_air(1.0) - pm100 - pm50 - pm25
#                pm5   = pm_data.pm_per_1l_air(0.5) - pm100 - pm50 - pm25 - pm10
#                pm3   = pm_data.pm_per_1l_air(0.3) - pm100 - pm50 - pm25 - pm10 - pm5

                self.latest_pms_readings = {
                    "particulate/1.0": pm_data.pm_ug_per_m3(1.0, atmospheric_environment=True),
                    "particulate/2.5": pm_data.pm_ug_per_m3(2.5, atmospheric_environment=True),
                    "particulate/10.0": pm_data.pm_ug_per_m3(None, atmospheric_environment=True),
                    "particulate/1.0-noatmos": pm_data.pm_ug_per_m3(1.0, atmospheric_environment=False),
                    "particulate/2.5-noatmos": pm_data.pm_ug_per_m3(2.5, atmospheric_environment=False),
                    "particulate/10-noatmos": pm_data.pm_ug_per_m3(10, atmospheric_environment=False),
                    "particulate/pm_per_1l_air0.3": pm_data.pm_per_1l_air(0.3),
                    "particulate/pm_per_1l_air0.5": pm_data.pm_per_1l_air(0.5),
                    "particulate/pm_per_1l_air1.0": pm_data.pm_per_1l_air(1.0),
                    "particulate/pm_per_1l_air2.5": pm_data.pm_per_1l_air(2.5),
                    "particulate/pm_per_1l_air5": pm_data.pm_per_1l_air(5),
                    "particulate/pm_per_1l_air10": pm_data.pm_per_1l_air(10),
                    "PMDATA": pm_data,


                }
            except:
                print("Failed to read from PMS5003. Resetting sensor.")
                traceback.print_exc()
                pms.reset()


    def take_readings(self):
        gas_data = gas.read_all()
        readings = {
            "proximity": ltr559.get_proximity(),
            "lux": ltr559.get_lux(),
            "temperature": self.bme280.get_temperature(),
            "pressure": self.bme280.get_pressure(),
            "humidity": self.bme280.get_humidity(),
            "gas/oxidising": gas_data.oxidising,
            "gas/reducing": gas_data.reducing,
            "gas/nh3": gas_data.nh3,
        }

        readings.update(self.latest_pms_readings)
        
        return readings


    def publish(self, topic, value):
        topic = self.prefix.strip("/") + "/" + topic
        #self.client.publish(topic, str(value))
        self.client.publish(topic, value)

    def update(self, publish_readings=True):
        self.samples.append(self.take_readings())

        if publish_readings:
            print (self.samples[0]["PMDATA"])

            for topic in self.samples[0].keys():
                if topic != "PMDATA":
                    value_sum = sum([d[topic] for d in self.samples])
                    value_avg = value_sum / len(self.samples)
                    self.publish(topic, value_avg)
                else:
                    self.publish(topic,str(self.samples[0]["PMDATA"]))


    def destroy(self):
        self.client.disconnect()
        self.client.loop_stop()
