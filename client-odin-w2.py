#! python3

from enum import Enum
import datetime
import argparse
import serial
import time
import collections
import re

Message = collections.namedtuple('Message', 'type content')

class OdinDataMode(Enum):
    CommandMode = 0
    DataMode = 1
    ExtendedDataMode = 2
    PPPMode = 3

OdinEdmSfd = b'\xAA'
OdinEdmEfd = b'\x55'
OdinCmSfd = b'\r\n'

class OdinEdmMsg(Enum):
    ConnEv = b'\x00\x11'
    DiscEv = b'\x00\x21'
    DataEv = b'\x00\x31'
    DataCmd = b'\x00\x36'
    AtEv = b'\x00\x41'
    AtReq = b'\x00\x44'
    AtConf = b'\x00\x45'
    ResendCmd = b'\x00\x56'
    iPhoneEv = b'\x00\x61'
    StartEv = b'\x00\x71'

class OdinWifiAuthType(Enum):
    Open = 1
    WPA = 2
    LEAP = 3
    PEAP = 4
    EAP_TLS = 5

class OdinIPV4Mode(Enum):
    Static = 1
    DHCP = 2

class OdinClient:
    def __init__(self, args):
        
        self.args = args
        self.__serial = serial.Serial(args.device, 115200)
        print('{} connected to {}'.format(datetime.datetime.now(), self.__serial.name))
        self.__serial.read(self.__serial.in_waiting)

        self.__dataMode = OdinDataMode.CommandMode
        self.__atCmdEcho = True
        self.__txContent = None

        if not self.reboot():
            raise Exception('Reboot failed')
        if not self.waitForStartup():
            raise Exception('Timed out when waiting for +STARTUP flag')

    def __txCommand(self, command):
        if self.__dataMode != OdinDataMode.CommandMode and self.__dataMode != OdinDataMode.ExtendedDataMode:
            raise Exception('Unsupported operation at data mode {}'.format(self.__dataMode.name))
        if self.__dataMode == OdinDataMode.CommandMode and self.__atCmdEcho == True:
            self.__txContent = command
        print('{} TX_CMD {}'.format(datetime.datetime.now(), command))
        self.__serial.write(command)

    def txData(self, data, channelId):
        if self.__dataMode != OdinDataMode.DataMode and self.__dataMode != OdinDataMode.ExtendedDataMode:
            raise Exception('Unsupported operation at data mode {}'.format(self.__dataMode.name))
        if self.__dataMode == OdinDataMode.ExtendedDataMode:
            dataLen = len(data) + len(OdinEdmMsg.DataCmd.value) + 1
            data = OdinEdmSfd + (chr(int(dataLen / 256)) + chr(dataLen % 256)).encode('ascii') \
                    + OdinEdmMsg.DataCmd.value + chr(channelId).encode('ascii') + data + OdinEdmEfd
        print('{} TX_DATA {}'.format(datetime.datetime.now(), data))
        self.__serial.write(data)

    #return True if a SFD is recived or False if receving timed out
    def __rxStartFrameDelimiter(self):
        if self.__dataMode == OdinDataMode.ExtendedDataMode:
            startFramePattern = OdinEdmSfd
        elif self.__dataMode == OdinDataMode.CommandMode:
            startFramePattern = OdinCmSfd
        else:
            raise Exception('Unsupported operation at data mode {}'.format(self.__dataMode.name))
        rxBuffer = self.__serial.read(len(startFramePattern))
        if len(rxBuffer) < len(startFramePattern):
            return False
        startFrame = rxBuffer
        while startFrame != startFramePattern:
            oneByte = self.__serial.read(1)
            if len(oneByte) < 1:
                return False
            rxBuffer += oneByte
            startFrame = startFrame[1:] + rxBuffer[-1:]
        print('{} RX_SFD {}'.format(datetime.datetime.now(), rxBuffer))
        return True

    #return None if receiving timed out or [] if no match message is received or [Messages] with all matched messages
    def rxMessageList(self, msgList):
        if self.__dataMode == OdinDataMode.ExtendedDataMode:
            if False == self.__rxStartFrameDelimiter():
                return None
            payloadLen = self.__serial.read(2)
            if len(payloadLen) < 2:
                return None
            payload = self.__serial.read(payloadLen[0] * 256 + payloadLen[1])
            if len(payload) < payloadLen[0] * 256 + payloadLen[1]:
                return None
            efd = self.__serial.read(1)
            if len(efd) < 1:
                return None
            edmMsgType = OdinEdmMsg(payload[:2])
            payload = payload[2:]
            if 0 == len(payload):
                payload = None
            print('{} RX_MSG x{:02x}x{:02x} {} {} x{:02x}'.format(datetime.datetime.now(), payloadLen[0], payloadLen[1], edmMsgType.name, payload, efd[0]))
            matchMsgList = [Message(type=x.type, content=payload) \
                            for x in msgList if x.type == edmMsgType \
                            and ((x.content is None) or (x.content is not None and x.content in payload))]
            return matchMsgList
        elif self.__dataMode == OdinDataMode.CommandMode:
            if self.__atCmdEcho == True and self.__txContent is not None:
                echoBackData = self.__serial.read(len(self.__txContent))
                if len(echoBackData) < len(self.__txContent):
                    return None
                print('{} RX_ECHO {}'.format(datetime.datetime.now(), echoBackData))
                self.__txContent = None
            if False == self.__rxStartFrameDelimiter():
                return None
            payload = b''
            while True:
                rxBuffer = self.__serial.readline()
                if not rxBuffer:
                    return None
                print('{} RX_MSG {}'.format(datetime.datetime.now(), rxBuffer))
                payload += rxBuffer
                matchMsgList = [Message(type=x.type, content=payload) for x in msgList if x.content in payload]
                if matchMsgList:
                    return matchMsgList
        else:
            raise Exception('Unsupported operation at data mode {}'.format(self.__dataMode.name))

    def rxMessage(self, message):
        return self.rxMessageList([message])

    def rxData(self):
        if self.__dataMode == OdinDataMode.DataMode:
            data = self.__serial.read(self.__serial.in_waiting)
            print('{} RX_DATA {}'.format(datetime.datetime.now(), data))
            return data
        elif self.__dataMode == OdinDataMode.ExtendedDataMode:
            data = self.rxMessage(Message(type=OdinEdmMsg.DataEv, content=None))
            if not data:
                return None
            data = data[0].content[1:]
            return data
        else:
            raise Exception('Unsupported operation at data mode {}'.format(self.__dataMode.name))

    def atCommand(self, command):
        if self.__dataMode != OdinDataMode.ExtendedDataMode and self.__dataMode != OdinDataMode.CommandMode:
            raise Exception('Unsupported operation at data mode {}'.format(self.__dataMode.name))
        payload = ('AT' + command + '\r').encode('ascii')
        if self.__dataMode == OdinDataMode.ExtendedDataMode:
            payloadLen = len(payload) + len(OdinEdmMsg.AtReq.value)
            payload = OdinEdmSfd + (chr(int(payloadLen / 256)) + chr(payloadLen % 256)).encode('ascii') + OdinEdmMsg.AtReq.value + payload + OdinEdmEfd
            expectedMsgList = [Message(type=OdinEdmMsg.AtConf, content=b'OK'), Message(type=OdinEdmMsg.AtConf, content=b'ERROR')]
        else:
            expectedMsgList = [Message(type=None, content=b'OK'), Message(type=None, content=b'ERROR')]
        self.__txCommand(payload)
        if len([x for x in self.rxMessageList(expectedMsgList) if b'ERROR' in x.content]):
            print('AT Command Failed')
            return False
        return True

    def atCommandNoWait(self, command):
        if self.__dataMode != OdinDataMode.ExtendedDataMode and self.__dataMode != OdinDataMode.CommandMode:
            raise Exception('Unsupported operation at data mode {}'.format(self.__dataMode.name))
        payload = ('AT' + command + '\r').encode('ascii')
        if self.__dataMode == OdinDataMode.ExtendedDataMode:
            payloadLen = len(payload) + len(OdinEdmMsg.AtReq.value)
            payload = OdinEdmSfd + (chr(int(payloadLen / 256)) + chr(payloadLen % 256)).encode('ascii') + OdinEdmMsg.AtReq.value + payload + OdinEdmEfd
        self.__txCommand(payload)
        return True

    def setStartMode(self, startMode):
        self.atCommand('+UMSM={}'.format(startMode))

    def storeConfiguration(self):
        self.atCommand('&W')

    def reboot(self):
        if self.atCommand('+CPWROFF'):
            self.__dataMode = OdinDataMode.CommandMode
            return True
        return False

    def waitForStartup(self):
        if self.__dataMode == OdinDataMode.CommandMode:
            if not self.rxMessage(Message(type=None, content=b'+STARTUP')):
                return False
            return True
        else:
            raise Exception('Unsupported operation at data mode {}'.format(self.__dataMode.name))
        
    def factoryReset(self):
        self.atCommand('+UFACTORY')

    def echoOff(self):
        if self.atCommand('E0'):
            self.__atCmdEcho = False
        
    def generalInfo(self):
        self.atCommand('+CGMI')
        self.atCommand('+CGMM')
        self.atCommand('+CGMR')
        self.atCommand('+CGSN')
        self.atCommand('+GMI')
        self.atCommand('+GMM')
        self.atCommand('+GSN')
        self.atCommand('I0')
        self.atCommand('I9')
        self.atCommand('I10')
        self.atCommand('+CSGT?')
    
    def activateWifiConfig(self, configId):
        self.atCommand('+UWSCA={},3'.format(configId))

    def deactivateWifiConfig(self, i):
        self.atCommand('+UWSCA={},4'.format(configId))

    def setWifiConfig(self, configId):
        args = self.args
        self.atCommand('+UWSC={},0,1'.format(configId))
        self.atCommand('+UWSC={},2,"{}"'.format(configId, args.ssid))
        self.atCommand('+UWSC={},5,{}'.format(configId, OdinWifiAuthType[args.auth].value))
        if OdinWifiAuthType[args.auth] == OdinWifiAuthType.WPA:
            self.atCommand('+UWSC={},8,"{}"'.format(configId, args.passphrase))
        self.atCommand('+UWSC={},100,{}'.format(configId, OdinIPV4Mode[args.ipv4mode].value))
        if OdinIPV4Mode[args.ipv4mode] == OdinIPV4Mode.Static:
            self.atCommand('+UWSC={},101,{}'.format(configId, args.ipv4addr))
            self.atCommand('+UWSC={},102,{}'.format(configId, args.ipv4mask))
            self.atCommand('+UWSC={},103,{}'.format(configId, args.ipv4gw))

    def disableRoaming(self):
        self.atCommand('+UWCFG=7,0')
        self.atCommand('+UWCFG=8,0')

    def setWifiForceWorldMode(self, mode):
        self.atCommand('+UWCFG=11,{}'.format(str(mode)))

    def radioReboot(self):
        self.atCommand('+UWCFG=0,0')
        self.atCommand('+UWCFG=0,1')

    def setNonDiscovery(self):
        self.atCommand('+UWTDM=1')

    def setConnectable(self):
        self.atCommand('+UWTCM=1')

    def setWifiChannelList(self, list):
        self.atCommand('+UWCL={}'.format(','.join([str(x) for x in list])))

    def getWifiChannelList(self):
        self.atCommandNoWait('+UWCL?')
        if self.__dataMode == OdinDataMode.ExtendedDataMode:
            respMsgList = odinClient.rxMessageList([Message(type=OdinEdmMsg.AtConf, content=b'OK'), Message(type=OdinEdmMsg.AtConf, content=b'ERROR')])
        elif self.__dataMode == OdinDataMode.CommandMode:
            respMsgList = odinClient.rxMessageList([Message(type=None, content=b'OK'), Message(type=None, content=b'ERROR')])
        else:
            raise Exception('Unsupported operation at data mode {}'.format(self.__dataMode.name))            
        if respMsgList and b'OK' in respMsgList[0].content:
            regex = re.compile('\+UWCL:([0-9](,[0-9]+)*)')
            sreMatch = regex.search(respMsgList[0].content.decode())
            if sreMatch:
                return sreMatch.group(1)
        return None

    def waitforWifiConnected(self, configId):
        if self.__dataMode == OdinDataMode.ExtendedDataMode:
            while True:
                if self.rxMessage(Message(type=OdinEdmMsg.AtEv, content=b'+UUWLE')):
                    return True
        elif self.__dataMode == OdinDataMode.CommandMode:
            while True:
                if (self.rxMessage(Message(type=None, content=b'+UUWLE'))):
                    return True
        else:
            raise Exception('Unsupported operation at data mode {}'.format(self.__dataMode.name))
        return False

    def waitforNetworkUp(self, interfaceId):
        if self.__dataMode == OdinDataMode.ExtendedDataMode:
            if self.rxMessage(Message(type=OdinEdmMsg.AtEv, content=b'+UUNU')):
                return True
        elif self.__dataMode == OdinDataMode.CommandMode:
            if self.rxMessage(Message(type=None, content=b'+UUNU')):
                return True
        else:
            raise Exception('Unsupported operation at data mode {}'.format(self.__dataMode.name))
        return False

    def getL3Addr(self, interfaceId):
        self.atCommandNoWait('+UNSTAT={},{}'.format(interfaceId, 101))
        if self.__dataMode == OdinDataMode.ExtendedDataMode:
            respMsgList = odinClient.rxMessageList([Message(type=OdinEdmMsg.AtConf, content=b'OK'), Message(type=OdinEdmMsg.AtConf, content=b'ERROR')])
        elif self.__dataMode == OdinDataMode.CommandMode:
            respMsgList = odinClient.rxMessageList([Message(type=None, content=b'OK'), Message(type=None, content=b'ERROR')])
        else:
            raise Exception('Unsupported operation at data mode {}'.format(self.__dataMode.name))            
        if respMsgList and b'OK' in respMsgList[0].content:
            regex = re.compile('\+UNSTAT:[0-9]+,[0-9]+,([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)')
            return regex.search(respMsgList[0].content.decode()).group(1)
        return None

    def connectToPeer(self, peerAddr, peerPort):
        self.atCommandNoWait('+UDCP="tcp://{}:{}/"'.format(peerAddr, peerPort))
        if self.__dataMode == OdinDataMode.ExtendedDataMode:
            respMsgList = odinClient.rxMessageList([Message(type=OdinEdmMsg.AtConf, content=b'OK'), Message(type=OdinEdmMsg.AtConf, content=b'ERROR')])
        elif self.__dataMode == OdinDataMode.CommandMode:
            respMsgList = odinClient.rxMessageList([Message(type=None, content=b'OK'), Message(type=None, content=b'ERROR')])
        else:
            raise Exception('Unsupported operation at data mode {}'.format(self.__dataMode.name))            
        if respMsgList and b'OK' in respMsgList[0].content:
            regex = re.compile('\+UDCP:([0-9]+)')
            return int(regex.search(respMsgList[0].content.decode()).group(1))
        return None

    def waitforPeerConnection(self, peerHandle):
        if self.__dataMode == OdinDataMode.ExtendedDataMode:
            messageList = self.rxMessage(Message(type=OdinEdmMsg.AtEv, content=b'+UUDPC'))
            if messageList:
                regex = re.compile('\+UUDPC:([0-9]+),')
                if peerHandle == int(regex.search(messageList[0].content.decode()).group(1)):
                    return True
            return False

        elif self.__dataMode == OdinDataMode.CommandMode:
            messageList = self.rxMessage(Message(type=None, content=b'+UUDPC'))
            if messageList:
                regex = re.compile('\+UUDPC:([0-9]+),')
                if peerHandle == int(regex.search(messageList[0].content.decode()).group(1)):
                    return True
            return False
        else:
            raise Exception('Unsupported operation at data mode {}'.format(self.__dataMode.name))

    def waitForConnectEvent(self, peerAddr, peerPort):
        if self.__dataMode == OdinDataMode.ExtendedDataMode:
            messageList = self.rxMessage(Message(type=OdinEdmMsg.ConnEv, content=None))
            if messageList:
                channelId = messageList[0].content[0]
                connectType = messageList[0].content[1]
                protocol = messageList[0].content[2]
                remoteAddr = str(messageList[0].content[3]) + '.' \
                    + str(messageList[0].content[4]) + '.' \
                    + str(messageList[0].content[5]) + '.' \
                    + str(messageList[0].content[6])
                remotePort = messageList[0].content[7] * 256 + messageList[0].content[8]
                if remoteAddr == peerAddr and remotePort == peerPort:
                    return channelId
        return None

    def setDataMode(self, mode):
        if self.atCommand('O{}'.format(mode.value)):
            self.__dataMode = mode
            if self.__dataMode == OdinDataMode.ExtendedDataMode:
                if self.rxMessage(Message(type=OdinEdmMsg.StartEv, content=None)):
                    return True
        return False
            
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-d', '--device', help='device (serial port)',
                        default='/dev/ttyUSB0')
    parser.add_argument('-s', '--host', help='hostname or address',
                        default='192.168.1.99')
    parser.add_argument('-p', '--port', help='port', type=int, default=25000)
    parser.add_argument('--ssid', help='SSID', default='SRBHA_OLA')
    parser.add_argument('--auth', help='authentication method',
                        default=OdinWifiAuthType.WPA.name, choices=[x.name for x in [OdinWifiAuthType.Open, OdinWifiAuthType.WPA]])
    parser.add_argument('--passphrase', help='passphrase',
                        default='12345678')
    parser.add_argument('--ipv4mode', help='ipv4mode',
                        default=OdinIPV4Mode.DHCP.name, choices=[x.name for x in OdinIPV4Mode])
    parser.add_argument('--ipv4addr', help='static ipv4 address',
                        default='0.0.0.0')
    parser.add_argument('--ipv4mask', help='static ipv4 net mask',
                        default='0.0.0.0')
    parser.add_argument('--ipv4gw', help='static ipv4 gateway',
                        default='0.0.0.0')
    args = parser.parse_args()

    odinClient = OdinClient(args)

    if not odinClient.setDataMode(OdinDataMode.ExtendedDataMode):
        print ('Switch to {} failed'.format(OdinDataMode.ExtendedDataMode.name))
        exit(-1)

    odinClient.generalInfo()
    configId = 0
    odinClient.setWifiConfig(configId)
    odinClient.getWifiChannelList()
    odinClient.setWifiForceWorldMode(0)
    odinClient.radioReboot()
    time.sleep(0.5)
    odinClient.setWifiChannelList([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 36, 40, 44, 48, 52, 56, 60, 64, 100, 104, 108, 112, 116, 132, 136, 140])
    odinClient.getWifiChannelList()
    #odinClient.setNonDiscovery()
    #odinClient.setConnectable()
    #odinClient.disableRoaming()
    odinClient.activateWifiConfig(configId)
    if not odinClient.waitforWifiConnected(configId):
        print('Wait for WIFI link establishment failed')
        exit(-2)
    interfaceId = 0
    if not odinClient.waitforNetworkUp(interfaceId):
        print('Wait for network up failed')
        exit(-3)
    print(odinClient.getL3Addr(interfaceId))
    if not odinClient.waitforNetworkUp(interfaceId):
        print('Wait for network up failed')
        exit(-4)
    print(odinClient.getL3Addr(interfaceId))
    peerHandle = odinClient.connectToPeer(args.host, args.port)
    channelId = odinClient.waitForConnectEvent(args.host, args.port)
    connected = odinClient.waitforPeerConnection(peerHandle)
    if not connected:
        print('Wait for peer connected failed')
        exit(-5)
    print('peer handle returned by UUDPC:{}'.format(peerHandle))
    dataToSend = b'P\n'
    while True:
        odinClient.txData(dataToSend, channelId)
        rxMsgList = odinClient.rxMessageList([Message(type=OdinEdmMsg.DataEv, content=None), \
            Message(type=OdinEdmMsg.AtEv, content=None), \
            Message(type=OdinEdmMsg.ConnEv, content=None), \
            Message(type=OdinEdmMsg.DiscEv, content=None), \
            Message(type=OdinEdmMsg.StartEv, content=None)])
        dataEv = [x for x in rxMsgList if x.type == OdinEdmMsg.DataEv]
        if dataEv:
            rxData = dataEv[0].content[1:]