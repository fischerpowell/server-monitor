# server-monitor
Raspberry Pi server room environment monitor. Monitors temperature, humidity, external power, and internet connection. Sends an alert via text message over Twilio's message API.  
##### Hardware Modules:  
&ensp; • DHT22 for temperature and humidity.  
&ensp; • WaveShare SIM7600X 4G Hat for cellular connection.  
&ensp; • MakerFocus UPS pack for power monitoring and backup power supply.  
&ensp; • LCD Screen with I2C backpack for display.  
  
## Concept Diagrams
### Graphic:
![Graphic Diagram](screens/diagram.png?raw=true "Title")
### Real:
![Real Diagram](screens/real.png?raw=true "Title")

  
  
## Setup Guide
### 1. Set up hardware  
##### &ensp; By default:
&emsp; a. DHT22 is wired into GPIO 17.  
&emsp; b. Button is wired into GPIO 4.  
&emsp; c. LCD is wired into the I2C pins.  
&emsp; d. UPS is wired into GPIO serial and configured as device ttyAMA0.  
&emsp; e. SIM Hat is connected using serial over usb, and enabled to run a ppp connection. 
### 2. Install Dependencies  
&ensp; pip3 install twilio rpi-lcd adafruit-dht  
