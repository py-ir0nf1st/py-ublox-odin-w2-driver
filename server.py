#! python3

import socketserver
import datetime
import argparse

class tcpHandler(socketserver.BaseRequestHandler):
    def handle(self):
        print('{}, {} connected, will echo everything received'.format(
                datetime.datetime.now(), self.request.getpeername()))
        while True:
            self.data = self.request.recv(1024)
            if not self.data:
                break
            self.request.sendall(self.data)
        print('{}, {} disconnected'.format(datetime.datetime.now(),
                                           self.request.getpeername()))
        
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-s', '--host', help='hostname or address',
                        default='0.0.0.0')
    parser.add_argument('-p', '--port', help='port', type=int, default=25000)
    args = parser.parse_args()
    socketserver.TCPServer.allow_reuse_address = True
    server = socketserver.TCPServer((args.host, args.port), tcpHandler)
    print('{}, starting TCP server (\'{}\', {})'.format(
            datetime.datetime.now(), args.host, args.port))
    server.serve_forever()
