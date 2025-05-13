"""
Usage: python3 rst_test.py server_ip server_port
"""

import socket
import sys
import datetime
import time

def localtime():
    # ISO 8601 <https://stackoverflow.com/a/28147286>
    return datetime.datetime.now().replace(microsecond=0).isoformat()

if __name__ == '__main__':
    # (server_ip, server_port)
    address = (sys.argv[1], int(sys.argv[2]))
    
    clientSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    clientSocket.settimeout(1)

    rdpPayload = b"GET /small.html HTTP/1.0\r\nConnection: close\r\n\r\n"
    rdpHeader = b'\n'.join([
        b'SYN|DAT|ACK|FIN',
        b'Sequence: 0',
        b'Length: ' + str(len(rdpPayload)).encode(),
        b'Acknowledgment: -1',
        b'Window: 5120',
        b'\n'
    ])
    rdpPacket = rdpHeader + rdpPayload

    for i in range(3):
        message = rdpHeader.replace(b'\n', b'; ')
        print(localtime() + ": Send; " + message.decode())
        
        clientSocket.sendto(rdpPacket, address)
        reply = b""
        
        try:
            reply, address = clientSocket.recvfrom(2048)
            print("Reply:", reply)
        except (socket.timeout, TimeoutError):
            print("Timeout")
        
        if b"RST" in reply:
            print("RST Received")
            break
       
        time.sleep(0.5)
