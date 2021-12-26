import collections, threading, traceback

import colorsys
import ST7735

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

from PIL import Image
from PIL import ImageDraw
from PIL import ImageFont
from fonts.ttf import RobotoMedium as UserFont
import logging


logging.basicConfig(
    format='%(asctime)s.%(msecs)03d %(levelname)-8s %(message)s',
    level=logging.INFO,
    datefmt='%Y-%m-%d %H:%M:%S')

# Create ST7735 LCD display class
st7735 = ST7735.ST7735(
    port=0,
    cs=1,
    dc=9,
    backlight=12,
    rotation=270,
    spi_speed_hz=10000000
)

# Initialize display
st7735.begin()
 
WIDTH = st7735.width
HEIGHT = st7735.height

# New canvas to draw on.
img = Image.new('RGB', (WIDTH, HEIGHT), color=(0, 0, 0))
draw = ImageDraw.Draw(img)

# Text settings.
font_size = 10
font = ImageFont.truetype(UserFont, font_size)
text_colour = (255, 255, 255)
back_colour = (0, 0, 0)

message = "Starting Up"
size_x, size_y = draw.textsize(message, font)

# Calculate text position
x = (WIDTH - size_x) / 2
y = (HEIGHT / 2) - (size_y / 2)

# Draw background rectangle and write text.
draw.rectangle((0, 0, 160, 80), back_colour)
draw.text((x, y), message, font=font, fill=text_colour)
st7735.display(img)

i = 0



def display_text(newline):
    global i
    global img

    if i==0:
        img = Image.new('RGB', (WIDTH, HEIGHT), color=(0, 0, 0))
 
    i = i + 1
    if i>5:
        i=0
        img = Image.new('RGB', (WIDTH, HEIGHT), color=(0, 0, 0))
   
 
    draw = ImageDraw.Draw(img)
    message=""
    message=message+newline
    
    # Write the text at the top in black
    draw.text((0, i*font_size), message, font=font, fill=(255,255,255))
    st7735.display(img)





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
        #if topic != "ENVIRO/PMDATA":
        #    display_text(right(str(topic)+str(value),20))
        if topic in ["ENVIRO/particulate/1.0","ENVIRO/particulate/2.5","ENVIRO/particulate/10.0","ENVIRO/temperature","ENVIRO/humidity"]:
            display_text(right(str(topic)+"-"+str(value),30))
            




    def update(self, publish_readings=True):
        global i
        self.samples.append(self.take_readings())

        if publish_readings:
            i=0
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



def left(s, amount):
    return s[:amount]

def right(s, amount):
    return s[-amount:]

def mid(s, offset, amount):
    return s[offset:offset+amount]