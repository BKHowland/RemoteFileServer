# RemoteFileServer
Written in Python, utilizing TCP socket programming to create a remote file server. This involved creating the server and client programs from scratch via queues and artificially limited data buffers. By submitting HTML format TCP requests to the server IP, the binary data of the requested files will be returned.

Completed March 2024

Simple Web Server (SWS) on RDP (SoR)

SoR specifications:
SoR packet format
RDP-COMMAND(S)
RDP-Header: Value
…
RDP-Header: Value
HTTP-COMMAND
HTTP-Header: Value
…
HTTP-Header: Value
HTTP-PAYLOAD

How to run SoR server:
python3 sor-server.py server_ip_address server_udp_port_number server_buffer_size server_payload_length

How to run SoR client:
python3 sor-client.py server_ip_address server_udp_port_number client_buffer_size client_payload_length
  read_file_name write_file_name [read_file_name write_file_name]*

