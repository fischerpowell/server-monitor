import adafruit_dht
from time import sleep, time
from sys import exit
from rpi_lcd import LCD
from gpiozero import Button
import multiprocessing
import serial
from twilio.rest import Client
import os
import socket
import signal
import configparser

config = configparser.ConfigParser()
config.read('setup.conf')

#Initializing devices. DHT (Sensor), LCD, Button, UPS

dht_device = adafruit_dht.DHT22(17)
lcd = LCD()
button = Button(4)

ups = serial.Serial(
    port='/dev/ttyAMA0',
    baudrate= 9600,
    parity=serial.PARITY_NONE,
    stopbits=serial.STOPBITS_ONE,
    bytesize=serial.EIGHTBITS,
    timeout=3)

#Initializing multiprocessing variables and setting them to default values.
#These defaults will ensure that the monitor is not triggered until a real data value is received.

temp = multiprocessing.Value('f', 0.0) #Float
humid = multiprocessing.Value('f', 0.0) #Float
bat_cap = multiprocessing.Value('i', 0) #Integer
conn = multiprocessing.Value('i', 0) #Integer, used as a boolean
pwr_status = multiprocessing.Value('i', 0) #Integer, used as a boolean
pon_function = multiprocessing.Value('i', 0) #Integer, used as a boolean

temp.value = 65.0 #Measured in degrees Fahrenheit
humid.value = 50 #Measured in rH
bat_cap.value = 100 #Percent out of 100, UPS battery capacity
conn.value = 1 #Used for internet connection. 1 is connected, 0 is disconnected
pwr_status.value = 1 #Used for external power. 1 is connected, 0 is disconnected.
pon_function.value = 0 #Used to start pon, for connecting to internet over sim. Setting to 1 calls the function to start.

screen = multiprocessing.Value('i', 0) #Integer
display = multiprocessing.Value('i', 0) #Integer, used as boolean.

screen.value = 0 #Used to track the screen that the LCD is displaying
display.value = 1 #Tracks whether to load the LCD screen. 1 is on, 0 is off.

#Initializing program constants.

screen_list = [0, 1, 2] #Possible screens. 0 is Temp/Humidity. 1 is Internet. 2 is Power

hold_time = 3 #How long to hold the button before toggling the display value

account_sid = config.get('twilio', 'account_sid') #Used for Twilio messenger. Values can be found when viewing the Messenging account details
auth_token = config.get('twilio', 'auth_token')
Client = Client(account_sid, auth_token)
messenger_number = config.get('twilio', 'messenger_number') #Phone number for Twilio messenger

check_conn_host = config.get('monitor', 'check_ip') #Host IP and port to be used when testing connection to the internet.
check_conn_port = int(config.get('monitor', 'check_port'))

location = config.get('general', 'location') #Location to announce when sending messages.
alert_list = config.get('general', 'alert_list') #List of phone numbers to send alerts to
message_dict = {'temp_hot' : 'Room temperature is too hot.\nCurrent Temperature: _PLACEHOLDER_ F',
                'temp_cold' : 'Room temperature is too cold.\nCurrent Temperature: _PLACEHOLDER_ F',
                'humid_high' : 'Room humidity is too high.\nCurrent Value: _PLACEHOLDER_ rH',
                'humid_low' : 'Room humidity is too low.\nCurrent Value: _PLACEHOLDER_ rH',
                'internet' : 'Internet connection status:\nDisconnected',
                'power' : 'External power unavailable.\nServer Monitor UPS Capacity: _PLACEHOLDER_%'
                } #Specific alert messages. Header is added in the message function, and the _PLACEHOLDER_ is filled in with multiprocessing values

debug = config.get('general', 'debug') #If this is set to true, the program will not actually send messages or start pon. Instead, messages will be displayed in terminal.

check_value_dict = {'temp' : [0,'range', float(config.get('monitor', 'temp_lowest')), float(config.get('monitor', 'temp_highest'))],
                    'humid' : [0, 'range', float(config.get('monitor', 'humidity_lowest')), float(config.get('monitor', 'humidity_highest'))],
                    'internet' : [0, 'bool'],
                    'power' : [0, 'bool']} #Dictionary used when monitoring values. A message is only sent after a value has been checked and failed three times.
#[0] counts how many times the value has been checked and failed, meaning a message will be sent after it reaches value 2
#[1] specifies the type of value it is. Temp and humid are integers that have to stay between a range and internet and power are booleans that have to be 1
#[2] and [3] are only included if the value is a range. [2] is the start of the range and [3] is the end. For example, temperature has to stay between 53.0 and 75.1 degrees F

minute_interval = int(config.get('monitor', 'minute_interval')) #How many minutes to wait between sending a warning message for the same monitored value.
#For example, after sending a message about the power, if the minute interval is set to 2, it will wait 2 minutes before sending another one
#This will not effect messages of different types. For example, if a message is sent about power, and then the internet goes out, it will not wait to send a message about the internet.

up_env_interval = int(config.get('monitor', 'up_env_interval')) #Intervals in seconds to be used when updating the different parameters. up_env_interval is for updating the temperature and humidity
up_conn_interval = int(config.get('monitor', 'up_conn_interval')) #Interval in seconds for testing the internet connection
up_power_interval = int(config.get('monitor', 'up_power_interval')) #Interval in seconds for testing external power connection
up_screen_interval = int(config.get('monitor', 'up_screen_interval')) #Interval in seconds for updating LCD screen
monitor_interval = int(config.get('monitor', 'monitor_interval')) #Interval in seconds for checking the monitored values.

#Normal functions to be used

def get_temp(): #Gets input from DHT sensor. Outputs temperature in degrees fahrenheit
    try:
        cel = dht_device.temperature #DHT outputs in celsius
        fah = 1.8 * cel + 32 #Converts to fahrenheit
        return fah 
    except (RuntimeError, TypeError) as e: #Filters out random errors thrown by dumb wire stuff. If a value is not returned by this function, the last temperature received is kept.
        if 'Checksum did not validate' or 'A full buffer was not returned' or "unsupported operand type(s) for *: 'float' and 'NoneType'" in e.args[0]:
            pass
        else:
            raise

def get_humid(): #Gets input from DHT sensor. Outputs value in relative humidity
    try:
        humidity = dht_device.humidity
        return humidity
    except RuntimeError as e: #Filters out random errors thrown. If a value is not returned by the function, the last rH value received is kept
        if 'Checksum did not validate' or 'A full buffer was not returned' in e.args[0]:
            pass
        else:
            raise
        
def send_message(value_name): #Used to send out warning messages. Value Name is the type of warning message sent, which uses the message_dict to build the message
    if conn.value == 0: #If internet is not connected (Need to use SIM Module)
        pon_function.value = 1 #Starts pon, which creates an internet connection over SIM. Runs for 60 seconds before terminating
        sleep(15) #15 seconds after starting pon, the message will be sent
    if check_value_dict[value_name][1] == 'range': #If value type is range
        range_low = check_value_dict[value_name][2] #stores the high and low values of the range
        range_high = check_value_dict[value_name][3]
        if value_name == 'temp': #If the message to be sent is a temperature warning
            if temp.value < range_low: #If the value is too low, send a cold warning
                message_id = 'temp_cold'
            elif temp.value > range_high: #If the valeu is too high, send a hot warning
                message_id = 'temp_hot'
            message = location + ' SERVER ALERT\n' + message_dict[message_id].replace('_PLACEHOLDER_', str(round(temp.value, 1))) #Replaces placeholder in the message with the current temperature.
        elif value_name == 'humid': #If the message to be sent is a humidity warning
            if humid.value < range_low: #If the value is too low, send a low warning
                message_id = 'humid_low'
            elif humid.value > range_high: #If the value is too high, send a high warning
                message_id = 'humid_high'
            message = location + ' SERVER ALERT\n' + message_dict[message_id].replace('_PLACEHOLDER_', str(round(humid.value, 1))) #Replaces placeholder in the message with the current Humidity level.
    else: #If value type is not range, meaning it is a boolean
        if value_name == 'power': #If the message to be sent is a power warning
            message_id = value_name
            message = location + ' SERVER ALERT\n' + message_dict[message_id].replace('_PLACEHOLDER_', str(bat_cap.value))#Replaces placeholder with current UPS battery percentage
        else:
            message_id = value_name
            message = location + ' SERVER ALERT\n' + message_dict[message_id]
    if debug == True:
        for phone_number in alert_list: #Simply prints out the message instead of actually sending it, so you don't accidentally spend money
            print('Message sent to "' + phone_number + '":')
            print(message)
    elif debug == False: #Sends out a message to every phone number in the alert_list
        for phone_number in alert_list:
            message = Client.messages.create(
                body=message,
                from_=messenger_number,
                to=phone_number
                )

def check_value(value_name): #Used to check that a monitored value is where it is supposed to be. Returns True or False. Input is the name of the value to check
    value_check = True #Initializes the check to True (passing). If the value fails, this bool will be set to false
    if check_value_dict[value_name][1] == 'range': #According to the value dictionary, if the value type should be between a range
        range_low = check_value_dict[value_name][2] #Stores the high and low values of the range
        range_high = check_value_dict[value_name][3]
        if value_name == 'temp': #If the checked value is temperature
            if temp.value < range_low or temp.value > range_high: #If multiprocessing temperature value is outside of the range
                value_check = False
        if value_name == 'humid': #If the checked value is humidity
            if humid.value < range_low or humid.value > range_high: #If multiprocessing humidity value is outside of the range
                value_check = False
    elif check_value_dict[value_name][1] == 'bool': #If the value type is a boolean. Boolean values pass if they are 1
        if value_name == 'internet': #If checked value is internet connection
            if conn.value == 0: #If internet connection is unavailable
                value_check = False
        if value_name == 'power': #If checked value is external power
            if pwr_status.value == 0: #If external power is unavailable
                value_check = False
    return value_check #Returns the results of the value check.

def start_pon(): #Function called to start pon. If pon_function.value is set to 1, the multiprocessing caller function will call this function.
    if debug == True: #Starting pon uses a minimal amount of data, so debug just sends a message to terminal
        print('Starting Pon...')
        sleep(60)
        print('Ending Pon...')
    elif debug == False:
        comm = os.popen('ip a|grep ppp0').read() #ppp0 is the connection type that the sim uses. 
        if comm == '': #If ppp0 is not listed as a connection type (If pon is not already running)
            pon_proc = subprocess.Popen(['sudo pon'], shell=True) #Runs the pon command
            sleep(60) #Sleeps for 60 seconds, which is ample time to send a message
            os.killpg(os.getpgid(pon_proc.pid), signal.SIGTERM) #Kills the pon process
    pon_function.value = 0 #Sets this value back to 0 after the function is called so it doesn't start an infinite loop.

#Multiprocessing functions. These run for the duration of the program.

def update_values(this_temp, this_humid): #Used to update the temperature and humidity multiprocessing values.
    while True: #this_temp and this_humid are the last temp/humidity values that were set.
        new_temp = get_temp()
        new_humid = get_humid()
        if new_temp == None:
            pass #If no value is returned by the temperature function, does not overwrite the last value given
        else:
            this_temp = new_temp
        if new_humid == None:
            pass #If no value is returned by the humdity function, does not overwrite the last value given
        else:
            this_humid = new_humid
        temp.value = this_temp #Sets the multiprocessing values for temperature and humidity. If they were not changed, keeps the last value given.
        humid.value = this_humid
        sleep(up_env_interval)

def check_button(): #Multiprocessing function to monitor the button presses
    while True:
        start_time = time() #Initializes button press start time 
        diff = 0 #Initializes difference between the start time and button release time
        while button.is_active and (diff < hold_time): #When button is pressed and the amount of time it's been held down is less than the amount required to trigger a secondary action
            now_time = time() #Gets current time
            diff = now_time - start_time #Sets difference to the current time minus the time at the start of the button press. This measures how long the press was.
            
        if diff < hold_time and diff != 0: #If the button was actually pressed and it was held down for less than the required hold time
            try:
                screen.value = screen_list[screen.value + 1] #Tries to increase the screen value by 1
            except IndexError:
                screen.value = 0 #If screen value is at the highest value already, loops it back to 0
            print('Pressed, screen = ' + str(screen.value))
            sleep(.5) #Sleeps for .5 seconds so it doesn't trigger a bunch of times or to fast. Basically button sensitivity
        elif diff > hold_time: #If held down for long enough to trigger secondary action
            if display.value == 1: #Toggles the display boolean. This does not disable the backlight, but the actual text.
                display.value = 0
            else:
                display.value = 1
            sleep(1)
    
def check_conn(): #Function used to monitor the internet connection
    while True:
        comm = os.popen('ip a|grep ppp0').read() #ppp0 is the connection type that the sim uses. 
        if comm == '': #If ppp0 is not listed as a connection type (If main internet connection is over wlan)
            try:
                socket.setdefaulttimeout(3) #Creates a socket to google over port 43 with a timeout tolerance of 3 seconds
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                server_address = (check_conn_host,check_conn_port)
                s.connect(server_address)
            except OSError: #If connection is unsuccessful
                conn.value = 0 #value of 0 indicates no connection
            else: #if connection is successful
                s.close() #closes socket
                conn.value = 1 #value of 1 indicates successful connection
        sleep(up_conn_interval)
        
def check_power(): #Used to monitor the external power connection
    while True:
        try:
            serial_data = str(ups.readline()).split(',') #UPS is set up as a serial device. Stores information sent
            ext_status = serial_data[1].replace('Vin ', '') #Data sent that confirms whether exernal power is connected
            batcap = serial_data[2].replace('BATCAP ', '') #Battery capacity percentage
            if 'GOOD' in ext_status: #If external power message contains "GOOD"
                pwr_status.value = 1 #pwr_status set to 1 indicates external power connection
            else:
                pwr_status.value = 0
            bat_cap.value = int(batcap) #Converts string sent over serial to integer
        except serial.SerialException: #Random wire errors
            pass
        sleep(up_power_interval)
    
def output_values(): #Used to output values to terminal and to the LCD screen
    while True:
        if display.value == 1: #If display is set to true.
            if screen.value == 0: #First screen, temp and humidity
                lcd.text('Temp: ' + str(round(temp.value, 1)) + ' F', 1)
                lcd.text('Hmd: ' + str(round(humid.value, 1)) + ' rH', 2)
                print('Temp: ' + str(round(temp.value, 1)) + ' F | Humidity: ' + str(round(humid.value, 1)) + ' rH')
            elif screen.value == 1: #Second screen, internet connection status
                if conn.value == 1: #If internet connection bool is true
                    print('Internet is connected.')
                    lcd.text('Internet Status:', 1)
                    lcd.text('Connected', 2)
                else: #if internet connection bool is false
                    print('No internet connection.')
                    lcd.text('Internet Status:', 1)
                    lcd.text('Not Connected', 2)
            elif screen.value == 2: #Third screen, power status
                if pwr_status.value == 1: #If external power bool is true
                    lcd.text('PWR Status: Good', 1)
                    print('PWR Status: Good | Battery: ' + str(bat_cap.value) + '%')
                else:
                    lcd.text('PWR Status: Bad', 1)
                    print('PWR Status: Bad | Battery: ' + str(bat_cap.value) + '%')
                lcd.text('Battery: ' + str(bat_cap.value) + '%', 2) #Second line indicates the battery percentage
        else: #Clear the screen if display is off
            lcd.clear()
        sleep(up_screen_interval)

def monitor_values(): #Used to check that the monitored values are where they should be.
    while True: #Sends a message if the value that is being checked has failed 3 times.
        for value_name in check_value_dict.keys(): #For all values to check
            if check_value(value_name) == False: #If value fails the check
                if check_value_dict[value_name][0] <= 2: #If value has failed the check less than 3 times in succession
                    check_value_dict[value_name][0] += 1 #Increases failed check counter by 1
                else: #If it has failed three times
                    send_message(value_name) #Send the warning message for whatever value has failed
                    check_value_dict[value_name][0] = -60 / monitor_interval * minute_interval + 4 #Monitor goes off every monitor_interval seconds, so this calculation changes the minute interval into second periods
            else:
                if check_value_dict[value_name][0] > 0:
                    check_value_dict[value_name][0] = 0 #If monitor succeeds, sets the counter to 0.
        sleep(monitor_interval)

def pon_caller(): #Used to start pon.
    while True: #Continuously checks whether pon_function.value is 1
        if pon_function.value == 1: #If the value is set to 1, calls the function to start pon
            start_pon() #start_pon sets the pon_function.value back to 0 at the end of it so a loop isn't created
        
        
#Initializes and starts all of the multiprocesses
update_value_func = multiprocessing.Process(target=update_values, args=(temp.value, humid.value))
out_value_func = multiprocessing.Process(target=output_values)
conn_func = multiprocessing.Process(target=check_conn)
power_func = multiprocessing.Process(target=check_power)
button_func = multiprocessing.Process(target=check_button)
monitor_func = multiprocessing.Process(target=monitor_values)
pon_func = multiprocessing.Process(target=pon_caller)

update_value_func.start()
out_value_func.start()
conn_func.start()
power_func.start()
button_func.start()
monitor_func.start()
pon_func.start()

#Keeps the program running and terminates all processes on Keyboard Interrupt. Also clears the lcd screen.
while True:
    try:
        pass
    except KeyboardInterrupt:
       update_value_func.terminate()
       out_value_func.terminate()
       conn_func.terminate()
       power_func.terminate()
       button_func.terminate()
       monitor_func.terminate()
       pon_func.terminate()
       lcd.clear()
       exit()