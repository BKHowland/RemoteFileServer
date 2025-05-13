import select
import socket
import sys
import queue
import time
import re


# ////////////////////////////IN PROGRESS///////////////////////////////
# Collected command line args, and added file requests to syn. Next is dealing with data? working on server to accept syn.
# 
# 
# ////////////////////////////TODO/////////////////////////////////
# try to request files that are more than payload size. expect everything to break. 
# Looks like the client is trying to say fin sent even when it is not on ack that has more data to come. 
# 
#via teams, although we can pack as much data as we can into a syn, we cant send more until it is acked. 

# RM LATER
import traceback



ECHO_SRV = ("10.10.1.100", 8888)

class rdpSender:
    # closed -> syn_sent -> open -> fin_sent -> closed
    state = "syn_sent"
    # Initialize sending buffer??
    snd_buf = queue.Queue()
    sws_requests_string = ""

    snd_seq_num = 0
    ack_num_rcvd = 0
    known_window = 1024
    unack_packets = {} #seq num, [packet data, timesent]. Stores any currently non-acked packets.
    prev_ack = 0
    dupe_acks = 0
    timeout_firstround = True
    rto = 1500 #ms to start
    srtt = 0
    rttvar = 0
    ack_time = 0 #(ms) time at which an ack was last recieved for timeout purposes.

    most_recent_sent_seq = 0

    # failcount = 0
    server_address = -1
    client_payload_length = 0
    client_buffer_size = 0

    finsentfirst = False
    finacknum = -1

    synsent = True
    synrecv = False
    finsent = False
    finrecv = False

    channelopen = False

    def open(self, rdp_receiver):
        # write SYN rdp packet into snd_buf, with max allowed data. 
        print("start of open rdp_receiver type: ", type(rdp_receiver))
        if (len(self.sws_requests_string) > self.client_payload_length):
            # requests take up more size than payload. add to syn and rm from string.
            print("requests to server take up more space than payload. sending syn without fin.")
            payload = self.sws_requests_string[0:self.client_payload_length]
            self.sws_requests_string = self.sws_requests_string[self.client_payload_length:]
            self.state = "syn_sent"
            rdp_receiver.state = "syn_sent"
            rdp_receiver.synsent = True
            self.synsent = True
            print("rdp_receiver type: ", type(rdp_receiver))
            packet_contents = "SYN|DAT|ACK\nSequence: 0\nLength: "+ str(len(payload)) +"\nAcknowledgment: -1\nWindow: "+ str(rdp_receiver.rcv_buf_window_max) + "\n\n"
        else:
            # requests string is less than payload, add all, empty it, can add fin to syn. 
            print("ALL REQUEST DATA CAN BE SENT AT ONCE IN OPEN. SYN AND FIN TOGETHER.")
            payload = self.sws_requests_string
            self.sws_requests_string = ""
            print("rdp_receiver type: ", type(rdp_receiver))
            packet_contents = "SYN|DAT|ACK|FIN\nSequence: 0\nLength: "+ str(len(payload)) +"\nAcknowledgment: -1\nWindow: "+ str(rdp_receiver.rcv_buf_window_max) + "\n\n"
            self.state = "fin_sent"
            self.finsent = True
            self.synsent = True
            self.finsent = True
            # rdp_receiver.state = "fin_sent"
            rdp_receiver.finsent = True
            rdp_receiver.synsent = True
            rdp_receiver.finsent = True
            self.finacknum = len(payload) + 1
            self.finsentfirst = True

        self.snd_seq_num += len(payload) + 1
        packet_contents += payload
        self.snd_buf.put(packet_contents.encode())

    def close(self):
        # write FIN packet to snd_buf
        packet_contents = "FIN\nSequence: " + str(self.snd_seq_num) + "\nLength: 0\n\n"
        self.snd_buf.put(packet_contents.encode())
        self.snd_seq_num += 1
        self.finacknum = self.snd_seq_num + 1
        self.state = "fin_sent"

    def check_timeout(self):
        if self.state != "closed":
            # if state is not closed and timeout HAS OCCURED: (deleted condition from if above)
            timeout_occur = False
            for unack in self.unack_packets: 
                if (((time.time()*1000) - self.unack_packets[unack][1]) > self.rto):
                    # rewrite the rdp packets into snd_buf
                    # timeout_occur = True
                    # I DONT KNOW IF TIMEOUT SHOULD BE PER PACKET OR JUST SINCE LAST RESPONSE///////////////////
                    # timeout for this packet has occured... resend and reset timer
                    self.unack_packets[unack][1] = time.time() * 1000 #time in ms.
                    # self.snd_buf.put(self.unack_packets[unack][0].raw_packet.encode())
                    self.snd_buf.put(self.unack_packets[unack][0].raw_packet)


            
            

    def rcv_ack(self, packet):
        print("in rcv_ack")
        # update known window value with that provided by receiver.
        if (packet.acknowledgment > self.most_recent_sent_seq):
            # dont want late acks to influence window size. 
            print("acknum greater than most resent sent sequence. updating known window")
            self.known_window = packet.window

        if (packet.acknowledgment == self.prev_ack):
            # recieved dupe acknum
            print("received dupe acknum")
            self.dupe_acks += 1

            if (self.dupe_acks >= 3):
                # after three duplicates, retransmit all that was not yet acked.
                for unacked in self.unack_packets:
                   self.snd_buf.put(self.unack_packets[unacked][0].raw_packet)
                self.dupe_acks = 0
                return #ignore the contents processing, we dont need it, was a dupe. 
        else:
            # new ack recieved. reset counter, update prev ack num
            print("new ack received")
            self.dupe_acks = 0
            self.prev_ack = packet.acknowledgment
            if(packet.command == "ACK"):
                # only ack. increment here. else leave it to data handler
                self.receiver_acknum += 1
            
            
            # update the rto based on ack.
            if(packet.sequence in self.unack_packets):
                # quick+dirty workaround for a rare key error.
                r = (time.time()*1000) - self.unack_packets[packet.sequence][1]
            else:
                r = 100
                # self.failcount += 1

            # time since sent ^ until now (recieved ack)
            if (self.timeout_firstround):
                #indicates that this is the first ack recieved.
                self.srtt = r
                self.rttvar = r/2
                self.rto = self.srtt + max(1, 4 * self.rttvar) #granularity of 1ms assumed?
                self.timeout_firstround = False
            else:
                alpha = 0.125
                beta = 0.25
                self.rttvar = (1 - beta) * self.rttvar + beta * abs(self.srtt - r)
                self.srtt = (1 - alpha) * self.srtt + alpha * r
                self.rto = self.srtt + max(1, 4 * self.rttvar)

            # remove any packets covered by new ack from unack dict.
            for unacked in list(self.unack_packets):
                if (packet.acknowledgment > self.unack_packets[unacked][0].sequence):
                    # if the given ack is above the sequence number sent, then it has been acked. remove. 
                    del self.unack_packets[unacked]

        
        
            
        print("self.state: ", self.state, " packet acknum: ", packet.acknowledgment, " snd_seq_num: ", self.snd_seq_num)
        if self.state == "syn_sent" or self.state == "fin_sent":
            # if (packet.acknowledgment == self.snd_seq_num + 1):
            if "ACK" in packet.command:
                # if ack # is correct? changed to just if acked. since we always syn.
                print("acknum correct for syn to open")
                # self.state = "open"
                # self.snd_seq_num += 1
                self.channelopen = True
        if self.state == "open":
            if (False):
                # if three duplicate received
                # rewrite the rdp packets into snd_buf
                # handled above
                pass
            if (False):
                # if acknum is correct
                # move the sliding window
                # write the available window of DAT rdp packets into snd_buf
                # if all data has been sent, call self.close()
                pass
                return
        if self.state == "fin_sent":  
            if (packet.acknowledgment == self.snd_seq_num + 1):
                print("acknum correct for closing based on fin sent")
                # if acknum is correct
                # if (rdp_receiver.state == "fin_acked"):
                self.state = "closed"
                rdp_receiver.state = "closed" #need to close here and break rdp otherwise a lost fin ack ruins everything.

            else:
                # ack was not for the fin.
                pass


class ack_response:
    def __init__(self):
        commands = ""
        headers = ""
        payload = b""
        sequence = -1
        acknowledgment = -1
        window = -1
        logentry = ""


def processSwsRequest(SWSresponse):
    #returns (content length, content) from response if present. else None.
    regex_result = re.search(b".*? (.*)\n([\s\S]*)\n\n([\s\S]*)", SWSresponse)
    # Group 1 is http response code and text (eg ok, not found), 2 is all headers, 3 is payload if any.
    if ("200 ok"  not in regex_result.group(1).lower() or "content-length" not in regex_result.group(2).lower()):
        # return none as either file not found, or content length header missing. 
        return None
    # else, we have a reply with file payload. 
    headers = regex_result.group(2)
    file_payload = regex_result.group(3)
    regex_result = re.search(b"[\s\S]*\r\nContent-Length: (.*)\r\n", headers, re.IGNORECASE)
    contentlength = regex_result.group(1).decode()

    return (int(contentlength), file_payload)


class rdpReceiver:
    # closed -> syn_sent -> open -> fin_sent -> closed
    state = "syn_sent"
    # Init receiving buffer (seqnum, packet data) dict
    rcv_buf = {}
    # final queue for data extraction only once packets are in order 
    rcv_final_buf = queue.Queue()
    temp_rcv_buf = b""
    rcv_buf_window_max = 5120
    # set initially to the max size, then change later. max is for checking data presence. 
    rcv_buf_window = rcv_buf_window_max
    rcv_buf_window_lastsent = rcv_buf_window_max # for determining when to update sender on the window size.
    rcv_buf_acknum = 0
    # rcv_exp_seqnum

    all_received = False

    server_address = -1
    client_payload_length = 0
    client_buffer_size = 0

    server_responses = b""

    synsent = True
    synrecv = False
    finsent = False
    finrecv = False

    sequence_num = 0

    channelopen = False

    serversfinacked = False
    finalacktimeout = 0
    finrcvseqnum = -1


    # //////////idk if reciever needs this
    def check_timeout(self):
        if self.state != "closed":
            # if self state is not closed and timeout has occured
            pass
            # rewrite the rdp packets into snd_buf
        

    def send_rst(self, sequencenum):
        response = ack_response()
        response.commands = "RST"
        response.acknowledgment = self.rcv_buf_acknum
        response.window = self.rcv_buf_window
        response.sequence = sequencenum
        self.state = "closed"
        rststring = "RST" + "\n" + "Sequence: " + str(sequencenum) + "\nAcknowledgment: " + str(self.rcv_buf_acknum)
        rststring += "\nWindow: " + str(self.rcv_buf_window) + "\nLength: 0\n\n"

        logentry = str(time.strftime("%a %b %d %H:%M:%S %Z %Y", time.localtime(time.time()))) + ": "
        logentry += "Send; RST;"
        print(logentry)
        bytes_sent = udp_sock.sendto((rststring).encode(), self.server_address)
        exit()


    def rcv_data(self, packet):
        response = ack_response()
        response.payload = b""
        response.sequence = self.sequence_num

        if(packet.command == "RST"):
            # received reset. terminate execution after informing user?
            self.state = "closed"
            rdp_sender.state = "closed"
            print("received reset. terminating.")
            exit()


        # HANDLE BROKEN CONVENTION
        if((len(packet.payload) > self.client_buffer_size)):
            print("convention broken, payload greater than buf size.")
            # convention broken. reset or ignore regardless of what they have to say. 
            # make sure its not closed without syn.
            if(self.state == "closed" and "SYN" not in packet.command):
                # in this case, we ignore because was not open, or closed with syn.
                return None
            else:
                # reset
                print("buffer size convention broken. resetting.")
                return self.send_rst(packet.sequence)

        # HANDLE PACKETS TO BE IGNORED
        if (self.state == "closed" and "SYN" not in packet.command):
            # packet without syn recieved before open. ignore?
            print("packet recieved without syn while closed...?")
            return None
        
        # HANDLE REPEAT PACKETS
        if ((packet.sequence < self.rcv_buf_acknum)):
            print("in case where sequence number is less than acknum. packet seq: ", packet.sequence, " rcvbuf acknum: ", self.rcv_buf_acknum)
            # packet recieved has sequence even less than previously acked. resend generic ack in case lost
            # do not change any sizes or store anything.
            # packet is also a dupe, but is above acknum so need to acknowledge without changing buffer.

            if (packet.sequence == self.finrcvseqnum):
                # it means we received a dupe of the server's fin meaning our ack was lost.
                # ack again as usual, but also update the timeout again.
                self.finalacktimeout = time.time()

            logentry = str(time.strftime("%a %b %d %H:%M:%S %Z %Y", time.localtime(time.time()))) + ": "
            logentry += "Send; ACK; Acknowledgment: " + str(self.rcv_buf_acknum) + "; Window: " + str(self.rcv_buf_window)
            print(logentry)
            # bytes_sent = udp_sock.sendto(("ACK\nAcknowledgment: "+str(self.rcv_buf_acknum)+"\nWindow: " + str(self.rcv_buf_window) +"\n\n").encode(), (server_address, server_port))
            unprocessed_packet = "ACK\nAcknowledgment: "+str(self.rcv_buf_acknum)+"\nWindow: " + str(self.rcv_buf_window) +"\n"
            unprocessed_packet += "Sequence: " + str(packet.sequence) + "\n\n" #for timeout purposes, seq # is returned.
            unprocessed_packet = unprocessed_packet.encode()
            return_packet = process_packet(unprocessed_packet)
            # bytes_sent = udp_sock.sendto((unprocessed_packet), self.client_address)
            return None #dont bother with the shenanigans below.
        
        # prepare basic response values
        response.commands = "ACK"
        response.acknowledgment = -1
        response.window = self.rcv_buf_window
        response.sequence = packet.sequence
        
        # HANDLE OPENING
        if (self.synsent == True and "SYN" in packet.command and self.finsent != True):
            # request to open connection. 
            if self.state == "closed":
                self.state = "syn_recv"
            self.synrecv = True
            print("opening client based on syn. sending ack.")
            logentry = str(time.strftime("%a %b %d %H:%M:%S %Z %Y", time.localtime(time.time()))) + ": "
            logentry += "Send; SYN|ACK; Acknowledgment: 1"+ "; Window: " + str(self.rcv_buf_window) 
            response.logentry = logentry
            self.rcv_buf_acknum = 1
            # print(logentry)

            # bugtesting ver for local only:
            # bytes_sent = udp_sock.sendto(("ACK\nAcknowledgment: 1\nWindow: " + str(self.rcv_buf_window) +"\n\n").encode(), (server_address, server_port))
            # for picolab
            response.acknowledgment = self.rcv_buf_acknum
        
        # Handle IGNORING WHEN CLOSED AND NOT SYN
        elif(self.state == "closed" and "SYN" not in packet.command):
            # closed and by above, it was not a syn. 
            print("we are closed and packet was not a syn.")
            return None
        
        # HANDLE UNEXPECTED SYN WHILE OPEN
        elif (self.state == "open" and "SYN" in packet.command):
            # recieved syn while open. Reset the connection? not sure..... maybe just remove this if it causes issues. could just
            # send default ack again...?
            print("recieved syn while open")
            return self.send_rst(packet.sequence)
        

        
        

        
        
    
        if ((("DAT" in packet.command) and (self.state == "open" or self.channelopen == True)) or ("DAT" in packet.command and "SYN" in packet.command)):
            # data recieved, either syn was included or have been open for a while. 
            print("in data handler")
            print("current rcv_buf ack number: ", self.rcv_buf_acknum)
            if (self.rcv_buf_window >= packet.length):
                # update the ack num based on data length and stored packets (gap check)
                # self.rcv_buf_acknum = self.rcv_buf_acknum + packet.length
                if (packet.sequence < self.rcv_buf_acknum):
                    # packet is a retransmitted and unneeded packet. do nothing
                    print("retransmitted packet that we have already")
                    # we need to send default ack here?
                    pass

                elif (packet.sequence > self.rcv_buf_acknum):
                    print("sequence greater than acknum")
                    # # packet is also a dupe, but is above acknum so need to acknowledge without changing buffer.
                    # logentry = str(time.strftime("%a %b %d %H:%M:%S %Z %Y", time.localtime(time.time()))) + ": "
                    # logentry += "Send; ACK; Acknowledgment: " + str(self.rcv_buf_acknum) + "; Window: " + str(self.rcv_buf_window)
                    # # print(logentry)
                    # # bytes_sent = udp_sock.sendto(("ACK\nAcknowledgment: "+str(self.rcv_buf_acknum)+"\nWindow: " + str(self.rcv_buf_window) +"\n\n").encode(), (server_address, server_port))
                    # unprocessed_packet = "ACK\nAcknowledgment: "+str(self.rcv_buf_acknum)+"\nWindow: " + str(self.rcv_buf_window) +"\n"
                    # unprocessed_packet += "Sequence: " + str(packet.sequence) + "\n\n" #for timeout purposes, seq # is returned.
                    # unprocessed_packet = unprocessed_packet.encode()
                    # return_packet = process_packet(unprocessed_packet)
                    pass
                    # bytes_sent = udp_sock.sendto((unprocessed_packet), self.client_address)

                else:
                    # packet is equal to acknum. need to loop through all buffered valid packets to get to new acknum.
                    if (len(packet.payload) == packet.length):
                        print("payload equals length.")
                        if("SYN" in packet.command and self.state == "closed"):
                            self.state = "syn_recv" #since other case opening is when no data.
                        # packet may be truncated by the echo server. guard against it. if not same, drop it.
                        # store in buffer (Dict with key = sequence num and value = packet)
                        self.rcv_buf[packet.sequence] = packet #fine to replace existing data if same seq num.

                        # update the window size based on the data received
                        self.rcv_buf_window = self.rcv_buf_window - packet.length
                        
                        window_restored = 0
                        while (self.rcv_buf_acknum in self.rcv_buf):
                            # while the current acknum has data in buffer associated with it...
                            # put the data (unpacked) into the final file write buffer as its now next in order
                            print("in final buffer extractor loop")
                            self.rcv_final_buf.put(self.rcv_buf[self.rcv_buf_acknum].payload)
                            # advance acknum based on the length
                            old_acknum = self.rcv_buf_acknum
                            self.rcv_buf_acknum = self.rcv_buf_acknum + self.rcv_buf[self.rcv_buf_acknum].length
                            # remove that transfered item from dictionary (no longer our problem) + expand window by len
                            window_restored += self.rcv_buf[old_acknum].length
                            del self.rcv_buf[old_acknum]

                        # once the loop is complete, no more in order data is present, now we ack with the most
                        # up-to-date acknum based on what data we actually acknowledge as being written. 
                        

                        
                        # process ack based on buffer window
                        # logentry = str(time.strftime("%a %b %d %H:%M:%S %Z %Y", time.localtime(time.time()))) + ": "
                        # logentry += "Send; ACK; Acknowledgment: " + str(self.rcv_buf_acknum) + "; Window: " + str(self.rcv_buf_window)
                        # # print(logentry)
                        # # bytes_sent = udp_sock.sendto(("ACK\nAcknowledgment: "+str(self.rcv_buf_acknum)+"\nWindow: " + str(self.rcv_buf_window) +"\n\n").encode(), (server_address, server_port))
                        # unprocessed_packet = "ACK\nAcknowledgment: "+str(self.rcv_buf_acknum)+"\nWindow: " + str(self.rcv_buf_window) +"\n"
                        # unprocessed_packet += "Sequence: " + str(packet.sequence) + "\n\n" #for timeout purposes, seq # is returned.
                        # unprocessed_packet = unprocessed_packet.encode()
                        # return_packet = process_packet(unprocessed_packet)
                        # # bytes_sent = udp_sock.sendto((unprocessed_packet), self.client_address)
                        print("length is equal to payload length. updating acknum for response.")
                        response.acknowledgment = self.rcv_buf_acknum
                        # or "FIN" in packet.command and self.finsent == True
                        if (("SYN" in packet.command and self.synsent == True)):
                            self.rcv_buf_acknum += 1
                            response.sequence += 1
                        response.window = self.rcv_buf_window

                        # update window size after sending based on data transfered 
                        self.rcv_buf_window += window_restored
                    else:
                        # packet is corrupt, ignore.
                        print("packet is corrupt. len != payload")
                        pass
                    
                    
            else:
                # buffer is probably full? convention broken, reset connection.
                print("buffer is probably full? convention broken, reset connection.")
                return self.send_rst(packet.sequence)


        if ("FIN" in packet.command and rdp_sender.state == "fin_sent"):
            # sent fin, receiving fin back. need to ack then close
            # self.state = "closed"
            # rdp_sender.state = "closed"
            self.serversfinacked = True
            self.finalacktimeout = time.time() #save the time when final ack was sent, only close after certain wait in case ack lost.
            self.finrcvseqnum = packet.sequence #save this so we know when a repeat fin comes in for lost ack. 
        elif ("FIN" in packet.command):
            # received fin from other side first. decide how to react. 
            pass

            # /////////////////////////////////////////////////////////////////////////////////////
            # request contained in syn. check if complete, for every complete message, 
            # making this too hard for myself. just assume messages are always complete (for now.) COME BACK TO THIS!!!!!!!!!!!!!
            # self.server_responses += packet.payload
            
            # # print("RCV FINAL BUFFER: ", self.rcv_final_buf)
            # all_requests = re.split(b'\r\n\r\n', self.server_responses)
            # print("ALL REQUESTS: ", all_requests)
            # while len(all_requests) > 0 and all_requests[0] != b"":
            #     # take each request and deal with it.
            #     filename = processSwsRequest(all_requests[0] + b"\r\n\r\n")
            #     print("determined filename: " , filename)
            #     del all_requests[0] #remove that request

            #     try: 
            #         requested_file = open(filename, "rb")
            #         requested_file_binary = requested_file.read()
            #         totalbytes = len(requested_file_binary)
            #         print("opened requested file. Appending to responses_to_client. total bytes: ", totalbytes)
            #         # add the file binary to client responses list. include total length.
            #         responsestr = b"HTTP/1.0 200 OK\r\nConnection: keep-alive\r\nContent-Length: " + str(totalbytes).encode() + "\r\n\r\n"
            #         responsestr += requested_file_binary
            #         self.responses_to_client.append((responsestr, totalbytes, totalbytes))
                    
            #     except: 
            #         print("The requested file does not exist. adding response ")
            #         # file not found, add 404 to responses. 0 for Content-Length and remaining length.
            #         responsestr = b"HTTP/1.0 404 Not Found\r\nConnection: keep-alive\r\n\r\n"
            #         self.responses_to_client.append((responsestr, len(responsestr), len(responsestr)))
            
        # DO REGARDLESS OF WHAT KIND OF MESSAGE IS RECEIVED:
        # take up to the user defined payload size from the responses, add it to the response payload
        # multiple cases - either one response fills payload, or it takes multiple. 
        # response.payload = b""
        # print("responses to client: ", self.responses_to_client)
        # print("response payload before: ", response.payload)
        # while ((len(response.payload) < self.server_payload_length) and len(self.responses_to_client) != 0):
        #     # while the payload is less than we are allowed to send, and there is more responses to deal with
        #     if(self.responses_to_client[0][2] >= self.server_payload_length):
        #         print("adding what can fit from request reposne to payload")
        #         # remaining content in request is bigger than payload or equal. Take what can fit
        #         amount_to_move = self.server_payload_length - len(response.payload)
        #         response.payload += self.responses_to_client[0][0][0: amount_to_move]
        #         #update the response remaining to whatever was not taken.
        #         self.responses_to_client[0][0] = self.responses_to_client[0][0][amount_to_move:]
        #         self.responses_to_client[0][2] -= amount_to_move

        #     elif (self.responses_to_client[0][2] == 0):
        #         # no more data in this response to take. remove it.
        #         print("removing response as no more data to add")
        #         del self.responses_to_client[0]
            
        #     else:
        #         # more data in reponse to get, but less than the payload size.
        #         print("adding what is left of response to payload")
        #         amount_to_move = self.server_payload_length - len(response.payload)
        #         if(self.responses_to_client[0][2] <= amount_to_move):
        #             # we can fit all data from this response into the payload, and delete it
        #             response.payload += self.responses_to_client[0][0]
        #             del self.responses_to_client[0]

        # # we now have a response payload which is the maximum we can do. 
        # if (len(response.payload) != 0):
        #     response.commands += "|DAT" #add this header since we have a payload now. 

        # if(len(self.responses_to_client) == 0):
        #     # no more data to share
        #     response.commands += "|FIN"
        #     self.finsent = True
            
            # //////////////////////////////////////////////////////////////////////////////////////////////
        response.acknowledgment = self.rcv_buf_acknum
        print("returning response: ", vars(response))
        return response



class rdp_packet:
    def __init__(self):
        command = ""
        headers = ""
        sequence = -1
        acknowledgment = -1
        window = -1
        length = -1
        payload = ""
        raw_packet = ""


    






def close_connection(socket):
    # cleans socket data and disconnect
    del lastactive[socket]
    socket.close()



def process_packet(packet_data):
    # takes the data of one complete UDP packet and returns an object with each property extracted.
    print("Inside process_packet")
    print("Packet: ", packet_data)
    try:
        # WIP: (.*?|\|*)\\n(.*)\\n\\n
        if (not re.search(b"(.*)\n([.\w\W]*?)\n\n([.\w\W]*)", packet_data)):
            raise Exception("Input message was not complete.") 
        regex_result = re.search(b"(.*)\n([.\w\W]*?)\n\n([.\w\W]*)", packet_data)

        processed_packet = rdp_packet()
        processed_packet.command = regex_result.group(1).decode()
        processed_packet.headers = regex_result.group(2).decode()
        processed_packet.payload = regex_result.group(3)
        print("commands: ", processed_packet.command, " Headers: ", processed_packet.headers, " payload: ", processed_packet.payload)

        # extract individual headers if present and assign to object
        regex_result = re.search("Sequence: (.*)", processed_packet.headers)
        if (regex_result and regex_result.group(1) != ""):
            processed_packet.sequence = int(regex_result.group(1))
        
        regex_result = re.search("Acknowledgment: (.*)", processed_packet.headers)
        if (regex_result and regex_result.group(1) != ""):
            processed_packet.acknowledgment = int(regex_result.group(1))

        regex_result = re.search("Window: (.*)", processed_packet.headers)
        if (regex_result and regex_result.group(1) != ""):
            processed_packet.window = int(regex_result.group(1))

        regex_result = re.search("Length: (.*)", processed_packet.headers)
        if (regex_result and regex_result.group(1) != ""):
            processed_packet.length = int(regex_result.group(1))

        processed_packet.raw_packet = packet_data #store raw input for direct to send buf (sender error control)

        return processed_packet
        
    except Exception as error:
        # message is not valid. 
        # return default empty packet?

        print(sys.exc_info()) # REMOVE BEFORE HANDIN
        traceback.print_exc() 
        return rdp_packet()

    


# ///////////////START OF MAIN///////////////////

# Define the port you want the server to run on. collect args. FORMAT:

# python3 sor-client.py server_ip_address server_udp_port_number client_buffer_size
# client_payload_length read_file_name write_file_name [read_file_name write_file_name]*
try: 
    server_address = sys.argv[1]
    server_port = int(sys.argv[2])
    SERVER_ADDR = (server_address, server_port)
    client_buffer_size = int(sys.argv[3])
    client_payload_length = int(sys.argv[4])

    read_file_names = []
    write_file_names = []

    filenameslist = sys.argv[5:len(sys.argv)]
    if(len(filenameslist) % 2 != 0):
        # given file names are not even number. invalid.
        raise "Invalid number of arguments"
    # print("filenameslist: ", filenameslist)

    for i in range(len(filenameslist)):
        # Loop over all command line file names, put in appropreate list. 
        if (i%2 == 0):
            # at an index with a readfile name
            read_file_names.append(filenameslist[i])
        else:
            # write file name index
            write_file_names.append(filenameslist[i])

    # print("readfilenames list: ", read_file_names)
    # print("writefilenames list: ", write_file_names)

except Exception as e:
    print("The arguments ", sys.argv, " are not recognized. Try again.")
    print(sys.exc_info()) # REMOVE BEFORE HANDIN
    traceback.print_exc() 
    sys.exit()



except:
    print("error, could not open file to write based on names provided. Please try a different name.")
    print(sys.exc_info()) # REMOVE BEFORE HANDIN
    traceback.print_exc() 
    sys.exit()


# TEMPORARILY MAKING THIS LONGER FOR INITIAL TESTING. CHANGE BACK AFTER!!!!!!!!!!!!!!!!!!!
timeout = 30

# ////////////////////////////////////////CLIENT DOES NOT NEED TO BIND
# Create a UDP socket
udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
# Allow address reuse
udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
# Set the socket to non-blocking mode
udp_sock.setblocking(0)
# Bind address, server_address is defined by the input
# udp_sock.bind((server_address, server_port))

# # UDP is not connection based.
# # Listen for incoming connections
# udp_sock.listen(5)


# single packet data packet space to build until complete. 
data_packet_builder = ""


# IDK IF NEED ANY OF THIS ANYMORE:///////////////////////////
# Outgoing message queues (socket:Queue)
response_messages = {}
# Incoming message
request_messages = {}
# define last socket activity for timeout purposes (socket:lastreqtime)
lastactive = {}
# define connection types for response handling (socket:connection_type)
requested_connection = {}

rdp_sender = rdpSender()
rdp_sender.server_address = SERVER_ADDR
rdp_sender.client_payload_length = client_payload_length
rdp_sender.client_buffer_size = client_buffer_size
rdp_receiver = rdpReceiver()
rdp_receiver.server_address = SERVER_ADDR
rdp_receiver.client_payload_length = client_payload_length
rdp_receiver.client_buffer_size = client_buffer_size
rdp_receiver.rcv_buf_window_max = client_buffer_size

print("initialization: rdp_receiver type: ", type(rdp_receiver))

outbound_requests_string = ""
for i in range(len(read_file_names)):
    # if (i != len(read_file_names)-1):
    if True:
        # a requested file that is not the last one
        outbound_requests_string += "GET /" + read_file_names[i] + " HTTP/1.0\r\nConnection: keep-alive\r\n\r\n"
    else:
        # requested file is last one. Do we use connection close for this?
        pass

print("outbound sws request messages: ", outbound_requests_string)
# save to sender so that it can send with sequence.
rdp_sender.sws_requests_string = outbound_requests_string


# send the initial syn
print("before open, rdp_receiver type: ", type(rdp_receiver))
rdp_sender.open(rdp_receiver)
rdp_receiver.synsent = True
rdp_receiver.finsent = rdp_sender.finsent
rdp_receiver.state = rdp_sender.state
rdp_receiver.sequence_num = rdp_sender.snd_seq_num
all_response_data = b""
while (rdp_sender.state != "closed") or (rdp_receiver.state != "closed"):
    readable, writable, exceptional = select.select([udp_sock], [udp_sock], [udp_sock], timeout)
    if udp_sock in readable:
        # receive data and append it into temp rcv_buf
        # SET THIS NUMBER TO MAX UDP PACKET SIZE, BUT DONT KNOW IF RIGHT. WONT KNOW PACKET SIZE AHEAD OF TIME. 
        rdp_receiver.temp_rcv_buf += (udp_sock.recv(65535))
        print("\nRECEIVER BUFFER: ", rdp_receiver.temp_rcv_buf, "\n")
        
        packets = []
        # if the message in rcv_buf is complete (detect a new line):
        while (re.search(b"\n\n", rdp_receiver.temp_rcv_buf)):
            # in this case, we have at least one message up to the header complete.
            # want to consume all complete packets.
            # extract the message from temp rcv_buf
            # split the message into RDP packets

            # get all lines
            buffer_lines = re.split(b'\n', rdp_receiver.temp_rcv_buf)
            # Get the command type of the first command
            # If command is data, extra processing needed. else it can be looked at immediately. 
            if(b"DAT" in buffer_lines[0]):
                # data packet received. check to see if both sides open. if not, have to rst???
                # if(rdp_sender.state == "open" or rdp_receiver.state == "open"):
                buffer_lines = re.split(b"\n\n", rdp_receiver.temp_rcv_buf)
                packet = process_packet((buffer_lines[0]+b"\n\n"))
                packets.append(packet)
                # length of subsequent data now in packet.length header field.
                # Since the RDP packet cant be larger than UDP, we know that the remaining data is here. 
                buffer_lines.remove(buffer_lines[0])
                rdp_receiver.temp_rcv_buf = b"\n\n".join(buffer_lines)
                # remaining is now data payload plus any other dregs. pull it out
                packet.payload = rdp_receiver.temp_rcv_buf[0:(packet.length)]
                # leave behind everything after data in temp buffer. 
                rdp_receiver.temp_rcv_buf = rdp_receiver.temp_rcv_buf[packet.length:]

                # else:
                #     # data packet was sent without both sides being open. deal w/ accordingly. RST?
                #     pass

                    
            else:
                # packet without payload. just add it to packets to deal with.
                print("processing packet without payload")
                buffer_lines = re.split(b"\n\n", rdp_receiver.temp_rcv_buf)
                packet = process_packet((buffer_lines[0]+b"\n\n"))
                packets.append(packet)
                # remove the dealt with packet and restore the temp buffer to the remaining ones. 
                buffer_lines.remove(buffer_lines[0])
                rdp_receiver.temp_rcv_buf = b"\n\n".join(buffer_lines)


        # TODO: those above loops dont actually construct the packets list properly   

        for packet in packets:
            # loop through packets that were received and forward them on as needed. 
            logentry = str(time.strftime("%a %b %d %H:%M:%S %Z %Y", time.localtime(time.time()))) + ": "
            # complex doohickey for removing extra sequence number
            headers = "; ".join((packet.headers.replace("\n", "; ")).split("; ")[0:2])
            logentry += "Receive; " + packet.command + "; " + headers
            print(logentry)
            print("packet recieved: ", vars(packet))

            if(packet.command == "ACK"):
                # only ack present. update sequence numbers
                rdp_sender.rcv_ack(packet)
                rdp_receiver.state = rdp_sender.state
                rdp_receiver.channelopen = rdp_sender.channelopen
                # rdp_receiver.rcv_buf_acknum += 1
                rdp_receiver.sequence_num = rdp_sender.snd_seq_num

            elif("ACK" in packet.command):
                # ack with other stuff
                # deal with any state changes required
                print("acknum before rcv ack ack and else case: ", rdp_receiver.rcv_buf_acknum)
                rdp_sender.receiver_acknum = rdp_receiver.rcv_buf_acknum
                isfinacked = rdp_sender.rcv_ack(packet)
                rdp_receiver.channelopen = rdp_sender.channelopen
                print("acknum after rcv ack ack and else case: ", rdp_receiver.rcv_buf_acknum)
                
                rdp_receiver.sequence_num = rdp_sender.snd_seq_num
                print("handling data/syn/etc receiver packet")
                rdp_receiver.state = rdp_sender.state
                print("handling data/syn/etc receiver packet w/ ack")
                response = rdp_receiver.rcv_data(packet)
                rdp_sender.state = rdp_receiver.state
                rdp_sender.receiver_acknum = rdp_receiver.rcv_buf_acknum
                print("acknum after rcv data ack and else case: ", rdp_receiver.rcv_buf_acknum)
                # rdp_receiver.rcv_buf_acknum += len(packet.payload)
                rdp_sender.receiver_acknum = rdp_receiver.rcv_buf_acknum
                rdp_sender.receiver_cur_window = rdp_receiver.rcv_buf_window
                rdp_sender.state = rdp_receiver.state

                # testing: 
                if (response == None):
                    break

                print("response: ", response)
                if (response != None):
                    print("\nRETURNED RESPONSE:\n", vars(response), "\n")
                    if (response.commands == "RST"):
                        # data receiver determined conventions broken. terminate client. it has been sent in receiver.
                        rdp_sender.state = "closed"
                        rdp_receiver.state = "closed"
                        break
                    if ("FIN" in response.commands):
                        rdp_sender.finsent = True
                        rdp_sender.state = "fin_sent"
                    # if ("FIN" in packet.command):
                    #     rdp_receiver.finrcv = True
                    #     rdp_receiver.state = "fin_rcv"
                    # if packet.command == "ACK":
                    # if "ACK" in packet.command:
                else: print("packet response returned None...")
                # only case handled by sender - all else is figured out in receiver "data"
                rdp_sender.ack_num_rcvd = packet.acknowledgment
                # response = rdp_sender.rcv_ack(packet)
                
                send_packet = response.commands + "\nSequence: " + str(rdp_sender.snd_seq_num) + "\nAcknowledgment: " + str(response.acknowledgment)
                send_packet +="\nLength: " + str(len(response.payload)) + "\nWindow: " + str(response.window)
                send_packet += "\n\n"
                # encode just the headers string and concat the binary (dont encode). diff encodings is fine? regex later
                send_packet = send_packet.encode()
                send_packet += response.payload
                print("response payload: ", response.payload)
                if (len(response.payload) > 0):
                    rdp_sender.snd_seq_num += response.payload
                    rdp_receiver.sequence_num = rdp_sender.snd_seq_num
                else:
                    rdp_sender.snd_seq_num += 1
                    rdp_receiver.sequence_num = rdp_sender.snd_seq_num
                rdp_sender.snd_buf.put(send_packet)
                print("\n Final sendpacket: ", send_packet, "\n")

            else:
                # no ack present, only other stuff
                print("handling data/syn/etc receiver packet, no ack")
                response = rdp_receiver.rcv_data(packet)
                rdp_sender.receiver_acknum = rdp_receiver.rcv_buf_acknum
                print("acknum after rcv dat no ack case: ", rdp_receiver.rcv_buf_acknum)
                # rdp_receiver.rcv_buf_acknum += len(packet.payload) #WE ONLY INCREMENT ACK NUM IF VALID IN ORDER!
                rdp_sender.receiver_acknum = rdp_receiver.rcv_buf_acknum
                rdp_sender.receiver_cur_window = rdp_receiver.rcv_buf_window
                rdp_sender.state = rdp_receiver.state
                # rdp_receiver.rcv_buf_acknum += len(packet.payload)

                if (response == None):
                    break

                print("response: ", response)
                if (response != None):
                    print("\nRETURNED RESPONSE:\n", vars(response), "\n")
                    if (response.commands == "RST"):
                        # data receiver determined conventions broken. terminate client. it has been sent in receiver.
                        rdp_sender.state = "closed"
                        rdp_receiver.state = "closed"
                        break
                    if ("FIN" in response.commands):
                        rdp_sender.finsent = True
                        rdp_sender.state = "fin_sent"
                    # if ("FIN" in packet.command):
                    #     rdp_receiver.finrcv = True
                    #     rdp_receiver.state = "fin_rcv"
                    # if packet.command == "ACK":
                    # if "ACK" in packet.command:
                else: print("packet response returned None...")
                # only case handled by sender - all else is figured out in receiver "data"
                rdp_sender.ack_num_rcvd = packet.acknowledgment
                # response = rdp_sender.rcv_ack(packet)
                
                
                
                
                
                send_packet = response.commands + "\nSequence: " + str(rdp_sender.snd_seq_num) + "\nAcknowledgment: " + str(response.acknowledgment)
                send_packet +="\nLength: " + str(len(response.payload)) + "\nWindow: " + str(response.window)
                send_packet += "\n\n"
                # encode just the headers string and concat the binary (dont encode). diff encodings is fine? regex later
                send_packet = send_packet.encode()
                send_packet += response.payload
                print("response payload: ", response.payload)
                if (len(response.payload) > 0):
                    rdp_sender.snd_seq_num += response.payload
                    rdp_receiver.sequence_num = rdp_sender.snd_seq_num
                else:
                    rdp_sender.snd_seq_num += 1
                    rdp_receiver.sequence_num = rdp_sender.snd_seq_num
                rdp_sender.snd_buf.put(send_packet)
                print("\n Final sendpacket: ", send_packet, "\n")




            if rdp_receiver.all_received == True and rdp_sender.finsentfirst == False:
                # all info received. send fin from this side as havent yet
                rdp_sender.close()

    if ((udp_sock in writable) ):
        # In our case, socket will almost always be writable.
        while (rdp_sender.snd_buf.qsize() > 0):
            # send buffer is not empty, something to send. loop through all available and send. 
            logentry = str(time.strftime("%a %b %d %H:%M:%S %Z %Y", time.localtime(time.time()))) + ": "
            unprocessed_packet = rdp_sender.snd_buf.get_nowait()
            packet = process_packet(unprocessed_packet)
            logentry += "Send; " + packet.command + "; " + packet.headers.replace("\n", "; ")
            print(logentry)

            # update sender's sequence number to that of the last packet sent. 
            # rdp_sender.snd_seq_num = packet.sequence

            # bytes_sent = udp_sock.sendto(unprocessed_packet.encode(), (server_address, server_port))
            # bytes_sent = udp_sock.sendto(unprocessed_packet.encode(), ECHO_SRV)


            # TEMPORARILY REMOVED THIS IN PLACE OF PRINT UNTIL SERVER IS READY.///////////////////////////////////////////////////
            bytes_sent = udp_sock.sendto(unprocessed_packet, SERVER_ADDR)
            # bytes_send = unprocessed_packet
            # print("SENDTO: PACKET: ", unprocessed_packet, " server: ", ECHO_SRV)


            # add packet to the unack list for error control
            if (packet.command != "ACK"):
                print("\nadding packet to unack_packets\n")
                # dont store plain ack packets for timeout.
                rdp_sender.unack_packets[packet.sequence] = [packet, time.time()*1000] #store time for timeout check(ms)
            rdp_sender.most_recent_sent_seq = packet.sequence
            # remove the bytes already sent from snd_buf
            # THIS MIGHT BE BUGGY AS **** BECAUSE IDK WHAT DAMN DATATYPE TO USE OR THE FORMAT WITHIN IT.
            
            # rdp_sender.snd_buf = rdp_sender.snd_buf[bytes_sent:]
 

        if(rdp_receiver.state == "open" or rdp_receiver.state == "fin_recv"):
            # only send things if either we are open, or if we are dealing with a syn-ack combo.
            # file_data = b""
            while (rdp_sender.known_window >= 1024):
                # while we know we have more space to send stuff, line up more stuff to send (if exists). 
                # file_data = requested_file.read(1024)
                # file_data = file_data.decode()
                if(current_byte + 1024 <= totalbytes):
                    # 1024 bytes or more left to read
                    file_data = requested_file_binary[current_byte:(current_byte+1024)]
                    current_byte += 1024
                elif(current_byte < totalbytes):
                    # less than 1024 bytes to read... watch out for inclusivity here!
                    file_data = requested_file_binary[current_byte : totalbytes]
                    # update current byte to be more than total
                    current_byte += totalbytes
                else:
                    # no more bytes to read
                    file_data = b""
                
                if ((file_data != b"")):
                    # pull more data from the file, and prepare the packet to send. 
                    # file_data = requested_file.read(1024)
                    send_packet = "DAT\nSequence: " + str(rdp_sender.snd_seq_num) + "\nLength: " + str(len(file_data))
                    send_packet += "\n\n"
                    # encode just the headers string and concat the binary (dont encode). diff encodings is fine? regex later
                    send_packet = send_packet.encode()
                    send_packet += file_data

                    rdp_sender.snd_buf.put(send_packet)

                    # update own sequence number based on the data sent.
                    rdp_sender.snd_seq_num = rdp_sender.snd_seq_num + len(file_data)
                    rdp_receiver.sequence_num = rdp_sender.snd_seq_num
                    # subtract the used space from the known window.
                    rdp_sender.known_window -= len(file_data)


                elif((file_data == b"") and rdp_sender.state == "open"):
                    # request to close the connection since work is done, and not waiting on space.
                    if ((rdp_sender.snd_seq_num == rdp_sender.ack_num_rcvd) and (rdp_sender.state)):
                        rdp_sender.close()
                        break
                    else:
                        # break to prevent blocking wait
                        break
                else:
                    # means waiting on window, or waiting on close ack, so dont do anything
                    break
            # after while, no more space to send (from beginning or after adding more data)
            # rdp_sender.check_timeout()
    



    # check for any data to write to file. NOTE, NOW THE FINAL RCV BUF MAY HAVE MULTIPLE FILE RESPONSES IN IT. 
    window_before_write = rdp_receiver.rcv_buf_window
    while (not rdp_receiver.rcv_final_buf.empty()):
        # while there is still data that has been sorted and ready to write...
        try:
            # get more data that is in order.
            all_response_data += rdp_receiver.rcv_final_buf.get_nowait()
            # rdp_receiver.rcv_buf_window += len(data)
        except queue.Empty:
            # should not occur...
            pass
    
    window_after_write = rdp_receiver.rcv_buf_window
    # if (window_after_write - window_before_write >= (rdp_receiver.rcv_buf_window_max / 2)):
    #     # if more than half of the window has been restored, send as new message. 
    #     pass

    print("\nmain loop states. Sender: ", rdp_sender.state, " Receiver: ", rdp_receiver.state, "\n")

    if(rdp_receiver.serversfinacked == True and (time.time() - rdp_receiver.finalacktimeout) > 1.5):
        # we have sent ack for server's final fin and enough time has passed to assume the ack wasnt lost.
        rdp_sender.state = "closed"
        rdp_receiver.state = "closed"

    rdp_sender.check_timeout()
    # time.sleep(0.5)

# after this, both sides are closed once again. 


# now we need to extract all data from the returned files. 
# all responses contained in all_response_data. deal with one at a time. 
current_file_index = 0
while (len(all_response_data) != 0):
    print("remaining response_data: ", all_response_data)
    response = re.split(b'\r\n\r\n', all_response_data)[0] #get first sws header.
    # if (response == b""):
    #     break
    print("response pulled from all_response_data: ", response)
    regex_result = re.search(b".*? (.*)\r\n([\s\S]*)", response, re.IGNORECASE)
    # http response type in G1, headers in G2
    if b"200 ok" not in regex_result.group(1).lower():
        # this case, the file was not found. no output file generated. remove and move to next
        print("request for file ", read_file_names[current_file_index], " provided no return file data.")
        all_response_data = all_response_data[len(response) + 4:]
        current_file_index += 1
        
    else:
        # file data must be present. 
        
        openfile = open(write_file_names[current_file_index], "wb")
        regex_result = re.search(b"[\s\S]*Content-Length: (.*)", regex_result.group(2), re.IGNORECASE) #get content length
        contentlength = int(regex_result.group(1))
        # remove the sws headers from response data
        all_response_data = all_response_data[len(response) + 4:]
        # what is left must be filename first
        file_data = all_response_data[:contentlength]
        print("request for file ", read_file_names[current_file_index], " provided file data: ", file_data)
        all_response_data = all_response_data[contentlength:] #remove extracted portion.
        openfile.write(file_data)
        openfile.close()
        current_file_index += 1






# FOR TESTING ONLY ///////////////////////////////////////////////
# import os
# import filecmp
# print("file comparison result... Are files the same? ", filecmp.cmp(read_file_name, write_file_name))
# cmpstring = "cmp -b " + read_file_name + " " + write_file_name
# print("cmp output if difference exists: ")
# os.system(cmpstring)
# print("failcount: ", rdp_sender.failcount)
# DELETE BEFORE HANDIN!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

