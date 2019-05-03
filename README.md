# py-ublox-odin-w2-driver
WIFI station driver for u-blox ODIN-W2 module written in Python

This driver is developed for testing purpose only. In my application senario, I use a Linux host to control a ODIN-W2 module throught a UART interface and configure the module to work as a WIFI station, so this driver is coming with pretty limited functions. If you need a full functional driver for this module, refer to another public available repository https://github.com/u-blox/ublox-odin-w2-drivers-binary-mbed-3

server.py: A stupid TCP server which echos back everything received from the connected client

client-odin-w2.py: A stupid TCP client which setup the ODIN-W2 module to firstly establish a WIFI link to a given AP and secondly connect to the TCP server through a UART interface.

Topology of testing setup:

&nbsp;|&nbsp;|&nbsp;|&nbsp;|&nbsp;|&nbsp;|&nbsp;
------|------------|--|-------------|-------|--------|------
Server|<-net link->|AP|<-WIFI link->|ODIN-W2|<-UART->|Client

All information needed by this implementation are from public available documents:

ODIN-W2 Datasheet

https://www.u-blox.com/sites/default/files/ODIN-W2_DataSheet_%28UBX-14039949%29.pdf

u-connect AT command manual

https://www.u-blox.com/sites/default/files/u-connect-ATCommands-Manual_%28UBX-14044127%29.pdf

u-blox Extended Data Mode

https://www.u-blox.com/sites/default/files/ExtendedDataMode_ProtocolSpec_%28UBX-14044126%29.pdf
