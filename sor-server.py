import select
import socket
import sys
import queue
import time
import re


# ////////////////////////////IN PROGRESS///////////////////////////////
# in the middle of reconfiguring rcv_data to support new multi-commands. progress written on the line with error. 
# 
# 
# ////////////////////////////TODO/////////////////////////////////
# CHECK HOW MUCH WE SHOULD INCREMENT ACKNUM BY FOR SYNS AND FINS WITH DATA. JUST DATA AMOUNT? OR DATA + 1????? 
# Is the client meant to remain open for more FINs until the ack is def received on the other side? not sure. Ask someone. 
# think about it as two channels and write it out. 
# 
# question in teams check answer. 


# RM LATER
import traceback

ECHO_SRV = ("10.10.1.100", 8888)

class rdpSender:
    # closed -> syn_sent -> open -> fin_sent -> closed
    state = "closed"
    # Initialize sending buffer??
    snd_buf = queue.Queue()
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

    client_address = -1

    server_payload_length = 0
    server_buffer_size = 0

    synsent = False
    synrecv = False
    finsent = False
    finrecv = False
    
    # failcount = 0
    receiver_acknum = 0
    receiver_cur_window = -1

    cansend = False

    donesending = False



    def open(self):
        # WE DONT NEED THIS ANYMORE SINCE SERVER SENDS AS MUCH AS POSSIBLE. 
        # write SYN rdp packet into snd_buf
        print("opening rdpSender")
        packet_contents = "SYN\nSequence: 0\nLength: 0\n\n"
        self.snd_buf.put(packet_contents.encode())
        self.snd_seq_num += 1
        self.state = "syn_sent"

    def close(self):
        # write FIN packet to snd_buf
        packet_contents = "FIN\nSequence: " + str(self.snd_seq_num) + "\nLength: 0\nAcknowledgment: " + str(self.receiver_acknum) + "\nWindow: "
        packet_contents += str(self.receiver_cur_window) + "\n\n"
        self.snd_buf.put(packet_contents.encode())
        self.snd_seq_num += 1
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

        
        
            

        if self.synsent == True:
            print("synsent is true")
            if (packet.acknowledgment == self.snd_seq_num + 1):
                # if ack # is correct
                print("ack num is correct to open for communication")
                self.state = "open"
                self.cansend = True
                self.snd_seq_num += 1
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
            print("in sender state fin sent, snd seq num + 1: ", self.snd_seq_num+1) 
            if (packet.acknowledgment == self.snd_seq_num):
                # if acknum is correct
                # removed plus 1 here as it is unclear how much we should be incrementing the acknum by when dat + fin
                self.state = "closed"
                self.donesending = True
                return True
                    # rdp_receiver.state = "closed" #need to close here and break rdp otherwise a lost fin ack ruins everything.

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


def processSwsRequest(SWSrequest):
    #returns plaintext filename from SWS request
    regex_result = re.search(b"GET /(.*) ", SWSrequest)
    return regex_result.group(1).decode()


class rdpReceiver:
    # closed -> syn_sent -> open -> fin_sent -> closed
    state = "closed"
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

    client_address = -1
    server_payload_length = 0
    server_buffer_size = 0

    client_requests = b""
    responses_to_client = [] #tuples with (response, total response length, remaining length)
    # ^^^^ changed to list of lists because tuples are immutable. 

    synsent = False
    synrecv = False
    finsent = False
    finrecv = False

    sequence_num = 0


    # //////////idk if reciever needs this
    def check_timeout(self):
        if self.state != "closed":
            # if self state is not closed and timeout has occured
            pass
            # rewrite the rdp packets into snd_buf
        
    def send_rst(self, sequencenum):
        print("sending reset")
        response = ack_response()
        response.commands = "RST"
        response.acknowledgment = self.rcv_buf_acknum
        response.window = self.rcv_buf_window
        response.sequence = sequencenum
        self.state = "closed"
        rststring = "RST" + "\n" + "Sequence: " + str(sequencenum) + "\nAcknowledgment: " + str(self.rcv_buf_acknum)
        rststring += "\nWindow: " + str(self.rcv_buf_window) + "\nLength: 0\n\n"

        logentry = str(time.strftime("%a %b %d %H:%M:%S %Z %Y", time.localtime(time.time()))) + ": "
        logentry += "RST;"
        print(logentry)
        bytes_sent = udp_sock.sendto((rststring).encode(), self.client_address)
        return response


    def rcv_data(self, packet):

        response = ack_response()
        # prepare basic response values
        response.commands = "ACK"
        response.acknowledgment = -1
        response.window = self.rcv_buf_window
        response.sequence = packet.sequence

        acknum_on_rcv = self.rcv_buf_acknum


        # if(packet.command == "RST"):
        #     # received reset. terminate execution after informing user?
            #  cant do this here as need to remove client sender too. intercept in main. 
        #     return "RST"

        # HANDLE BROKEN CONVENTION
        if((len(packet.payload) > self.server_buffer_size)):
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
        if ((packet.sequence < acknum_on_rcv and "ACK" not in packet.command) or (packet.sequence + 1 < acknum_on_rcv)):
            print("in case where sequence number is less than acknum.")
            # packet recieved has sequence even less than previously acked. resend generic ack in case lost
            # do not change any sizes or store anything.
            # packet is also a dupe, but is above acknum so need to acknowledge without changing buffer.
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
        if (self.state == "closed" and "SYN" in packet.command and "DAT" not in packet.command):
            # request to open connection. 
            self.state = "syn_recv"
            self.synrecv = True
            print("opening server based on syn in packet without data.")
            logentry = str(time.strftime("%a %b %d %H:%M:%S %Z %Y", time.localtime(time.time()))) + ": "
            logentry += "Send; SYN|ACK; Acknowledgment: 1"+ "; Window: " + str(self.rcv_buf_window) 
            response.logentry = logentry
            # print(logentry)

            # bugtesting ver for local only:
            # bytes_sent = udp_sock.sendto(("ACK\nAcknowledgment: 1\nWindow: " + str(self.rcv_buf_window) +"\n\n").encode(), (server_address, server_port))
            # for picolab
            response.commands = "SYN|" + response.commands #add this to commands on return.
            response.acknowledgment = 1
            self.rcv_buf_acknum = 1
            self.synsent = True
            return response
        
        # Handle IGNORING WHEN CLOSED AND NOT SYN
        elif(self.state == "closed" and "SYN" not in packet.command):
            # closed and by above, it was not a syn. 
            return None
        
        # HANDLE UNEXPECTED SYN WHILE OPEN
        elif (self.state == "open" and "SYN" in packet.command):
            # recieved syn while open. Reset the connection? not sure..... maybe just remove this if it causes issues. could just
            # send default ack again...?
            print("recieved syn while open")
            return self.send_rst(packet.sequence)
        

        
        

        
        
    
        elif ((("DAT" in packet.command) and self.state == "open") or ("DAT" in packet.command and "SYN" in packet.command)):
            # data recieved, either syn was included or have been open for a while. 
            print("in data handler")
            print("current rcv_buf ack number: ", self.rcv_buf_acknum)
            if (self.rcv_buf_window >= packet.length):
                # update the ack num based on data length and stored packets (gap check)
                # self.rcv_buf_acknum = self.rcv_buf_acknum + packet.length
                if ((packet.sequence < acknum_on_rcv)):
                    # packet is a retransmitted and unneeded packet. do nothing
                    print("retransmitted packet that we have already")
                    # we need to send default ack here?
                    pass

                elif ((packet.sequence > acknum_on_rcv)):
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
                        if("SYN" in packet.command):
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
                        # print("recv buf acknum after pulling data: ", self.rcv_buf_acknum)
                        # response.acknowledgment = self.rcv_buf_acknum
                        # response.window = self.rcv_buf_window

                        # # update window size after sending based on data transfered 
                        # self.rcv_buf_window += window_restored
                        response.acknowledgment = self.rcv_buf_acknum
                        if ("SYN" in packet.command and self.synsent == True):
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
                self.state = "closed"
                return self.send_rst()
                # print(logentry)
                # bytes_sent = udp_sock.sendto((rststring).encode(), self.client_address)


            # /////////////////////////////////////////////////////////////////////////////////////
            # request contained in syn. check if complete, for every complete message, 
            # making this too hard for myself. just assume messages are always complete (for now.) COME BACK TO THIS!!!!!!!!!!!!!
                
            # WILL NEED TO USE THIS RCV FINAL BUFFER STUFF TO SOLVE!
            # check for any data to write to file
            # window_before_write = rdp_receiver.rcv_buf_window
            # while (not rdp_receiver.rcv_final_buf.empty()):
            #     # while there is still data that has been sorted and ready to write...
            #     try:
            #         data = rdp_receiver.rcv_final_buf.get_nowait()
            #         # rdp_receiver.rcv_buf_window += len(data)
            #     except queue.Empty:
            #         # should not occur...
            #         pass
            #     file_to_write.write(data)
        
            # window_after_write = rdp_receiver.rcv_buf_window



            self.client_requests += packet.payload
            # print("RCV FINAL BUFFER: ", self.rcv_final_buf)
            all_requests = re.split(b'\r\n\r\n', self.client_requests)
            print("ALL REQUESTS: ", all_requests)
            while len(all_requests) > 0 and all_requests[0] != b"":
                # take each request and deal with it.
                filename = processSwsRequest(all_requests[0] + b"\r\n\r\n")
                print("determined filename: " , filename)
                del all_requests[0] #remove that request

                try: 
                    requested_file = open(filename, "rb")
                    requested_file_binary = requested_file.read()
                    totalbytes = len(requested_file_binary)
                    print("opened requested file. Appending to responses_to_client. total bytes: ", totalbytes)
                    # add the file binary to client responses list. include total length.
                    responsestr = b"HTTP/1.0 200 OK\r\nConnection: keep-alive\r\nContent-Length: " + str(totalbytes).encode() + b"\r\n\r\n"
                    responsestr += requested_file_binary
                    templist = [responsestr, totalbytes, totalbytes]
                    self.responses_to_client.append(templist)
                    
                except: 
                    print("The requested file does not exist. adding response ")


                    print(sys.exc_info()) # REMOVE BEFORE HANDIN
                    traceback.print_exc() 


                    # file not found, add 404 to responses. 0 for Content-Length and remaining length.
                    responsestr = b"HTTP/1.0 404 Not Found\r\nConnection: keep-alive\r\n\r\n"
                    templist = [responsestr, len(responsestr), len(responsestr)]
                    self.responses_to_client.append(templist)
            
            if ("SYN" in packet.command):
                # case where syn mixed with data
                # request to open connection. 
                self.state = "syn_recv"
                self.synrecv = True
                print("opening server based on syn in data handler.")
                logentry = str(time.strftime("%a %b %d %H:%M:%S %Z %Y", time.localtime(time.time()))) + ": "
                logentry += "Send; SYN|ACK; Acknowledgment: 1"+ "; Window: " + str(self.rcv_buf_window) 
                response.logentry = logentry
                # print(logentry)

                # bugtesting ver for local only:
                # bytes_sent = udp_sock.sendto(("ACK\nAcknowledgment: 1\nWindow: " + str(self.rcv_buf_window) +"\n\n").encode(), (server_address, server_port))
                # for picolab
                response.commands = "SYN|" + response.commands #add this to commands on return.
                response.acknowledgment += 1
                self.rcv_buf_acknum += 1
                self.synsent = True

            if ("FIN" in packet.command):
                # fin mixed with data. 
                self.state = "fin_recv"
                self.finrecv = True

        # if ("FIN" in packet.command):
        #     response.acknowledgment = self.rcv_buf_acknum
        #     print("recieved fin! returning ack reponse.")
        #     if(self.finsent == True):
        #         self.state = "closed"
        #     return response


        # DO REGARDLESS OF WHAT KIND OF MESSAGE IS RECEIVED:
        # take up to the user defined payload size from the responses, add it to the response payload
        # multiple cases - either one response fills payload, or it takes multiple. 
        

        return self.grabdata(response)

        

    



        # rststring = ""
        # THIS NEEDS TO BE CHANGED TO DIFFERENTIATE BECAUSE IF GREATER, IT SHOULD BE BUFFERED.
        # if ((packet.sequence < self.rcv_buf_acknum) or (packet.sequence > self.rcv_buf_acknum)):
        #     print("in weird first case recv data - sequence less or more than previous acked.")
        #     # packet recieved has sequence even less or more than previously acked. resend generic ack in case lost
        #     # do not change any sizes or store anything.
        #     # packet is also a dupe, but is above acknum so need to acknowledge without changing buffer.
        #     logentry = str(time.strftime("%a %b %d %H:%M:%S %Z %Y", time.localtime(time.time()))) + ": "
        #     logentry += "Send; ACK; Acknowledgment: " + str(self.rcv_buf_acknum) + "; Window: " + str(self.rcv_buf_window)
        #     print(logentry)
        #     # bytes_sent = udp_sock.sendto(("ACK\nAcknowledgment: "+str(self.rcv_buf_acknum)+"\nWindow: " + str(self.rcv_buf_window) +"\n\n").encode(), (server_address, server_port))
        #     unprocessed_packet = "ACK\nAcknowledgment: "+str(self.rcv_buf_acknum)+"\nWindow: " + str(self.rcv_buf_window) +"\n"
        #     unprocessed_packet += "Sequence: " + str(packet.sequence) + "\n\n" #for timeout purposes, seq # is returned.
        #     unprocessed_packet = unprocessed_packet.encode()
        #     return_packet = process_packet(unprocessed_packet)
        #     bytes_sent = udp_sock.sendto((unprocessed_packet), self.client_address)
        #     return None #dont bother with the shenanigans

        # if self.state == "open" and "SYN" in packet.command:
        #     # Reset the connection? not sure..... this is before open based on syn. 
        #     print("recieved syn while open")
        #     self.state = "closed"
        #     rststring = "RST" + "\n\n"
        #     logentry = str(time.strftime("%a %b %d %H:%M:%S %Z %Y", time.localtime(time.time()))) + ": "
        #     logentry += "RST;"
        #     print(logentry)
        #     # bytes_sent = udp_sock.sendto((rststring).encode(), self.client_address)
        #     exit()

        # if self.state == "closed":
            # if ("SYN" in packet.command):
            #     self.state = "open"
            #     print("opening server based on syn.")
            #     # send ack
            #     # rdp_sender.snd_buf.put("ACK\nAcknowledgment: 1\nWindow: \n\n")
            #     # DONT WANT RECIEVER USING THE SENDERS BUFFER.
            #     synopened = True
            #     if ("DAT" not in packet.command):
            #         print("syn with no data")
            #         logentry = str(time.strftime("%a %b %d %H:%M:%S %Z %Y", time.localtime(time.time()))) + ": "
            #         logentry += "Send; ACK; Acknowledgment: 1"+ "; Window: " + str(self.rcv_buf_window) 
            #         # print(logentry)

            #         # bugtesting ver for local only:
            #         # bytes_sent = udp_sock.sendto(("ACK\nAcknowledgment: 1\nWindow: " + str(self.rcv_buf_window) +"\n\n").encode(), (server_address, server_port))
            #         # for picolab
            #         ackstring = "ACK\nAcknowledgment: 1\nWindow: " + str(self.rcv_buf_window) +"\nSequence: " + str(packet.sequence) + "\n\n"
            #         # bytes_sent = udp_sock.sendto((ackstring).encode(), self.client_address)
            #         self.rcv_buf_acknum = 1

            # else:
            #     # drop it? or just ignore?
            #     pass
        # if self.state == "open": #can open on same message as syn now. changed to if
            # if ("SYN" in packet.command):
                # # Reset the connection? not sure.....
                # print("recieved syn while open")
                # self.state = "closed"
                # rststring = "RST" + "\n\n"
                # logentry = str(time.strftime("%a %b %d %H:%M:%S %Z %Y", time.localtime(time.time()))) + ": "
                # logentry += "RST;"
                # print(logentry)
                # bytes_sent = udp_sock.sendto((rststring).encode(), self.client_address)
                # exit()

            # if ("FIN" in packet.command):
            #     print("fin packet")
            #     # Reset the connection? not sure.....
            #     # NEED TO WAIT HERE TO MAKE SURE THAT THE SENDER DOES NOT MISS THE ACK BEFORE CLOSING!
            #     # rdp_sender.snd_buf.put("ACK\nAcknowledgment: 1\nWindow: \n\n")
            #     if ("DAT" not in packet.command and "SYN" not in packet.command):
            #         print("fin packet without data")
            #         self.rcv_buf_acknum += 1
            #         logentry = str(time.strftime("%a %b %d %H:%M:%S %Z %Y", time.localtime(time.time()))) + ": "
            #         logentry += "Send; ACK; Acknowledgment: " + str(self.rcv_buf_acknum) + "; Window: " + str(self.rcv_buf_window)
            #         print(logentry)
            #         # bytes_sent = udp_sock.sendto(("ACK\nAcknowledgment: "+str(self.rcv_buf_acknum)+"\nWindow: " + str(self.rcv_buf_window) +"\n\n").encode(), (server_address, server_port))
            #         unprocessed_packet = "ACK\nAcknowledgment: "+str(self.rcv_buf_acknum)+"\nWindow: " + str(self.rcv_buf_window) +"\n"
            #         unprocessed_packet += "Sequence: " + str(packet.sequence) + "\n\n" #for timeout purposes, the seq num is returned.
            #         unprocessed_packet = unprocessed_packet.encode()
            #         return_packet = process_packet(unprocessed_packet)
            #         # bytes_sent = udp_sock.sendto((unprocessed_packet), self.client_address)
            #     self.state = "fin_acked"
            #     # if rcv ack for fin is lost, receiver will keep syn_sent to infinity. 

            # if ("DAT" in packet.command): #changed to if because dat and fin can be in same. bugs ahoy.
            #     print("data packet")
            #     comparison_offset = 0 #to account for when syn is done with data, have to add to values.
            #     if(synopened):
            #         comparison_offset = 1
            #     if (self.rcv_buf_window >= 1024):
            #         # update the ack num based on data length and stored packets (gap check)
            #         # self.rcv_buf_acknum = self.rcv_buf_acknum + packet.length
            #         if (packet.sequence < self.rcv_buf_acknum):
            #             # packet is a retransmitted and unneeded packet. do nothing
            #             pass

            #         elif (packet.sequence > self.rcv_buf_acknum):
            #             # packet is also a dupe, but is above acknum so need to acknowledge without changing buffer.
            #             logentry = str(time.strftime("%a %b %d %H:%M:%S %Z %Y", time.localtime(time.time()))) + ": "
            #             logentry += "Send; ACK; Acknowledgment: " + str(self.rcv_buf_acknum) + "; Window: " + str(self.rcv_buf_window)
            #             # print(logentry)
            #             # bytes_sent = udp_sock.sendto(("ACK\nAcknowledgment: "+str(self.rcv_buf_acknum)+"\nWindow: " + str(self.rcv_buf_window) +"\n\n").encode(), (server_address, server_port))
            #             unprocessed_packet = "ACK\nAcknowledgment: "+str(self.rcv_buf_acknum)+"\nWindow: " + str(self.rcv_buf_window) +"\n"
            #             unprocessed_packet += "Sequence: " + str(packet.sequence) + "\n\n" #for timeout purposes, seq # is returned.
            #             unprocessed_packet = unprocessed_packet.encode()
            #             return_packet = process_packet(unprocessed_packet)
            #             # bytes_sent = udp_sock.sendto((unprocessed_packet), self.client_address)

            #         else:
            #             # packet is valid (may still be dupe above ack number)
            #             if (len(packet.payload) == packet.length):
            #                 # packet may be truncated by the echo server. guard against it. if not same, drop it.
            #                 # store in buffer (Dict with key = sequence num and value = packet)
            #                 self.rcv_buf[packet.sequence] = packet #fine to replace existing data if same seq num.

            #                 # update the window size based on the data received
            #                 self.rcv_buf_window = self.rcv_buf_window - packet.length
                            
            #                 window_restored = 0
            #                 while (self.rcv_buf_acknum in self.rcv_buf):
            #                     # while the current acknum has data in buffer associated with it...
            #                     # put the data (unpacked) into the final file write buffer as its now next in order
            #                     self.rcv_final_buf.put(self.rcv_buf[self.rcv_buf_acknum].payload)
            #                     # advance acknum based on the length
            #                     old_acknum = self.rcv_buf_acknum
            #                     self.rcv_buf_acknum = self.rcv_buf_acknum + self.rcv_buf[self.rcv_buf_acknum].length
            #                     # remove that transfered item from dictionary (no longer our problem) + expand window by len
            #                     window_restored += self.rcv_buf[old_acknum].length
            #                     del self.rcv_buf[old_acknum]

            #                 # once the loop is complete, no more in order data is present, now we ack with the most
            #                 # up-to-date acknum based on what data we actually acknowledge as being written. 
                            

                            
            #                 # process ack based on buffer window
            #                 logentry = str(time.strftime("%a %b %d %H:%M:%S %Z %Y", time.localtime(time.time()))) + ": "
            #                 logentry += "Send; ACK; Acknowledgment: " + str(self.rcv_buf_acknum) + "; Window: " + str(self.rcv_buf_window)
            #                 # print(logentry)
            #                 # bytes_sent = udp_sock.sendto(("ACK\nAcknowledgment: "+str(self.rcv_buf_acknum)+"\nWindow: " + str(self.rcv_buf_window) +"\n\n").encode(), (server_address, server_port))
            #                 unprocessed_packet = "ACK\nAcknowledgment: "+str(self.rcv_buf_acknum)+"\nWindow: " + str(self.rcv_buf_window) +"\n"
            #                 unprocessed_packet += "Sequence: " + str(packet.sequence) + "\n\n" #for timeout purposes, seq # is returned.
            #                 unprocessed_packet = unprocessed_packet.encode()
            #                 return_packet = process_packet(unprocessed_packet)
            #                 # bytes_sent = udp_sock.sendto((unprocessed_packet), self.client_address)

            #                 # update window size after sending based on data transfered 
            #                 self.rcv_buf_window += window_restored
            #             else:
            #                 # packet is corrupt, ignore.
            #                 pass
                        
            #     else:
            #         # buffer is probably full? convention broken, reset connection.
            #         self.state = "closed"
            #         rststring = "RST" + "\n\n"
            #         logentry = str(time.strftime("%a %b %d %H:%M:%S %Z %Y", time.localtime(time.time()))) + ": "
            #         logentry += "RST;"
            #         # print(logentry)
            #         # bytes_sent = udp_sock.sendto((rststring).encode(), self.client_address)
            #         exit()

                # if("SYN" in packet.command):
                #     self.rcv_buf_acknum += 1 #account for skipped incriment in syn. if done up there, breaks validity decision logic

            # else:
            #     # packet command was not recognized
            #     rststring = "RST" + "\n\n"
            #     logentry = str(time.strftime("%a %b %d %H:%M:%S %Z %Y", time.localtime(time.time()))) + ": "
            #     logentry += "RST;"
            #     # print(logentry)
            #     # bytes_sent = udp_sock.sendto((rststring).encode(), self.client_address)
        #     #     exit()
        # print(logentry)
        # if rststring == "": 
        #     bytes_sent = udp_sock.sendto(unprocessed_packet, self.client_address)
        # else: 
        #     bytes_sent = udp_sock.sendto((rststring).encode(), self.client_address)

    def grabdata(self, response):
        # NOTE, VAST CONFUSION WAS HAD DUE TO THE LENGTH OF THE INTERNAL SWS RESPONSE PAYLOAD AND THE LENGTH OF FULL RESPONSE
        # BEING MIXED UP.
        response.payload = b""
        print("responses to client: ", self.responses_to_client)
        print("response payload before: ", response.payload)
        while ((len(response.payload) < self.server_payload_length) and len(self.responses_to_client) != 0):
            print("while loop response payload len: ", len(response.payload))
            # while the payload is less than we are allowed to send, and there is more responses to deal with
            print("remaining length of current responses[0]: ", len(self.responses_to_client[0][0]))
            datamoved = b""
            if(len(self.responses_to_client[0][0]) >= self.server_payload_length):
                print("--------------adding what can fit from request reposne to payload")
                # remaining content in request is bigger than payload or equal. Take what can fit
                amount_to_move = self.server_payload_length - len(response.payload)
                print("amount can move: ", amount_to_move)
                datamoved = self.responses_to_client[0][0][0: amount_to_move]
                print("amount moved: ", len(datamoved))
                response.payload += datamoved
                #update the response remaining to whatever was not taken.
                self.responses_to_client[0][0] = self.responses_to_client[0][0][amount_to_move:]
                self.responses_to_client[0][2] -= amount_to_move

            elif (len(self.responses_to_client[0][0]) == 0):
                # no more data in this response to take. remove it.
                print("-------------removing response as no more data to add")
                del self.responses_to_client[0]
            
            else:
                # more data in reponse to get, but less than the payload size.
                print("------------adding what is left of response to payload: ", self.responses_to_client[0][0])
                amount_to_move = self.server_payload_length - len(response.payload)
                print("amount can move: ", amount_to_move)
                if(len(self.responses_to_client[0][0]) <= amount_to_move):
                    # we can fit all data from this response into the payload, and delete it
                    datamoved = self.responses_to_client[0][0]
                    print("amount moved: ", len(datamoved))
                    response.payload += datamoved
                    del self.responses_to_client[0]

        print("final payload len: ", len(response.payload))
        # we now have a response payload which is the maximum we can do. 
        if (len(response.payload) != 0):
            response.commands += "|DAT" #add this header since we have a payload now. 

        if(len(self.responses_to_client) == 0 and self.finrecv == True and self.finsent == False):
            # no more data to share, client is done
            response.commands += "|FIN"
            self.finsent = True
            
            # //////////////////////////////////////////////////////////////////////////////////////////////
        print("final response packet: ", vars(response))
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
    del http_lastactive[socket]
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



def packetHasCommand(packet_data, command):
    # takes in raw packet data received, and string of "ACK"/DAT/SYN/FIN to check if command is present.
    try:
        # WIP: (.*?|\|*)\\n(.*)\\n\\n
        if (not re.search(b"(.*)\n([.\w\W]*?)\n\n([.\w\W]*)", packet_data)):
            raise Exception("Input message was not complete.") 
        regex_result = re.search(b"(.*)\n([.\w\W]*?)\n\n([.\w\W]*)", packet_data)

        commands = regex_result.group(1).decode()
        if (command in commands):
            return True
        else:
            return False
    
    except Exception as error:
        # message is not valid. 
        # return default empty packet?

        print(sys.exc_info()) # REMOVE BEFORE HANDIN
        traceback.print_exc() 
        return False

def processedPacketHasCommand(packet_obj, command):
    # takes in raw packet data received, and string of "ACK"/DAT/SYN/FIN to check if command is present.
    if (command in packet_obj.command):
        return True
    else:
        return False
    


# ///////////////START OF MAIN///////////////////

# Define the port you want the server to run on. collect args.
# python3 sor-server.py server_ip_address server_udp_port_number server_buffer_size server_payload_length
try: 
    server_address = sys.argv[1]
    server_port = int(sys.argv[2])
    server_buffer_size = sys.argv[3]
    server_payload_length = sys.argv[4]
except:
    print("The arguments '"+sys.argv[1]+" "+sys.argv[2]+" "+ sys.argv[3]+" "+ sys.argv[4] +" are not recognized. Try again.")
    sys.exit()




# TEMPORARILY MAKING THIS LONGER FOR INITIAL TESTING. CHANGE BACK AFTER!!!!!!!!!!!!!!!!!!!
timeout = 30

# Create a UDP socket FOR ALL SERVER INPUTS
udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
# Allow address reuse
udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
# Set the socket to non-blocking mode
udp_sock.setblocking(0)
# Bind address, server_address is defined by the input
udp_sock.bind((server_address, server_port))

# # UDP is not connection based.
# # Listen for incoming connections
# udp_sock.listen(5)


# IDK IF NEED ANY OF THIS ANYMORE:///////////////////////////
# Outgoing message queues (socket:Queue)
response_messages = {}
# Incoming message
request_messages = {}


# define last socket activity for timeout purposes (socket:lastreqtime)
http_lastactive = {}

# define connection types for response handling (socket:connection_type)
requested_connection = {}

# rdp_sender = rdpSender()
# rdp_receiver = rdpReceiver()


# dictionary for each client. Key is the address, value tbd. 
clientslist = {}


# while (rdp_sender.state != "closed") or (rdp_receiver.state != "closed"):
# Since this is the server, we are always open and listening. above condition has to apply on a per-client basis. 
while True:
    readable, writable, exceptional = select.select([udp_sock], [udp_sock], [udp_sock], timeout)
    if udp_sock in readable:
        # receive data and append it into temp rcv_buf
        # SET THIS NUMBER TO MAX UDP PACKET SIZE, WONT KNOW PACKET SIZE AHEAD OF TIME. 
        # rdp_receiver.temp_rcv_buf += (udp_sock.recvfrom(65535)) old version.
        temp_rcv_tuple = (udp_sock.recvfrom(65535))
        print("Temp rcv_tuple: ", temp_rcv_tuple)
        # return type is (bytes, address) [0] is data received, [1] is the address of the client.
        client_address = temp_rcv_tuple[1]
        if (client_address in clientslist):
            # received message from existing client. update the timeout and handle it.
            http_lastactive[client_address] = time.time()
            pass
        
        else:
            # received message from new client. Create entry for the client and handle it. 
            new_sender = rdpSender()
            new_sender.client_address = client_address
            new_sender.server_buffer_size = int(server_buffer_size)
            new_sender.server_payload_length = int(server_payload_length)
            new_receiver = rdpReceiver()
            new_receiver.client_address = client_address
            new_receiver.server_buffer_size = int(server_buffer_size)
            new_receiver.server_payload_length = int(server_payload_length)
            clientslist[client_address] = [new_sender, new_receiver]
            http_lastactive[client_address] = time.time()

        # proceed to deal with packet...
        rdp_sender = clientslist[client_address][0]
        rdp_sender.client_address = client_address #store address of client in respective rdp sender class
        rdp_receiver = clientslist[client_address][1]
        rdp_receiver.temp_rcv_buf = temp_rcv_tuple[0] #store the payload in the same way as rdp.py
        
        packets = []
        # if the message in rcv_buf is complete (detect a new line):
        while (re.search(b"\n\n", rdp_receiver.temp_rcv_buf)):
            # in this case, we have at least one message up to the header complete.
            # want to consume all complete packets.
            # extract the message from temp rcv_buf
            # split the message into RDP packets

            # get all lines
            buffer_lines = re.split(b'\n', rdp_receiver.temp_rcv_buf)
            print("Buffer_lines: ", buffer_lines)
            # Get the command type(s) of the first command
            # If command is data, extra processing needed. else it can be looked at immediately. 
            # unprocessed_packet = re.split(b"\n\n", rdp_receiver.temp_rcv_buf)
            # print("unprocessed packet: ", unprocessed_packet)
            # if(buffer_lines[0] == b"DAT"):
            if(b"DAT" in buffer_lines[0]):
                # data packet received. check to see if both sides open. if not, have to rst??? THIS DOESNT APPLY ANYMORE. CAN GET DATA ON SYN!
                # if(rdp_sender.state == "open" or rdp_receiver.state == "open"):

                if (b"SYN" in buffer_lines[0] or rdp_receiver.state == "open"): #check that its not a lone data packet. CONDITION MAY CAUSE BUG
                    buffer_lines = re.split(b"\n\n", rdp_receiver.temp_rcv_buf)
                    packet = process_packet((buffer_lines[0]+b"\n\n")) #Here, we do not pass the payload itself?
                    packets.append(packet)
                    # length of subsequent data now in packet.length header field.
                    # Since the RDP packet cant be larger than UDP, we know that the remaining data is here. 
                    buffer_lines.remove(buffer_lines[0])
                    rdp_receiver.temp_rcv_buf = b"\n\n".join(buffer_lines)
                    # remaining is now data payload plus any other dregs. pull it out
                    packet.payload = rdp_receiver.temp_rcv_buf[0:(packet.length)]
                    print("data processed_packet: ", vars(packet))
                    # leave behind everything after data in temp buffer. 
                    rdp_receiver.temp_rcv_buf = rdp_receiver.temp_rcv_buf[packet.length:]

                else:
                    # data packet was sent without both sides being open. deal w/ accordingly. RST?
                    print("data packet recieved while not open")
                    pass


            # the above does not apply any longer since we have multi-command packets. will need to rewrite. 

                    
            else:
                # packet without payload. just add it to packets to deal with.
                buffer_lines = re.split(b"\n\n", rdp_receiver.temp_rcv_buf)
                packet = process_packet((buffer_lines[0]+b"\n\n"))
                print("else processed packet: ", packet)
                packets.append(packet)
                # remove the dealt with packet and restore the temp buffer to the remaining ones. 
                buffer_lines.remove(buffer_lines[0])
                rdp_receiver.temp_rcv_buf = b"\n\n".join(buffer_lines)

  

        for packet in packets:
            # loop through packets that were received and forward them on as needed. 
            logentry = str(time.strftime("%a %b %d %H:%M:%S %Z %Y", time.localtime(time.time()))) + ": "
            # complex doohickey for removing extra sequence number
            headers = "; ".join((packet.headers.replace("\n", "; ")).split("; ")[0:2])
            logentry += "Receive; " + packet.command + "; " + headers
            print(logentry)
            print("packet recieved: ", vars(packet))
            print("for packet loop receiver acknum: ", rdp_receiver.rcv_buf_acknum)


            if(packet.command == "RST"):
                # terminate this client slot in server
                rdp_sender.state = "closed"
                rdp_receiver.state = "closed"
                break

            elif(packet.command == "ACK"):
                # only ack present. update sequence numbers
                print("acknum before rcv ack ack only case: ", rdp_receiver.rcv_buf_acknum)
                rdp_sender.receiver_acknum = rdp_receiver.rcv_buf_acknum
                isfinacked = rdp_sender.rcv_ack(packet)
                rdp_receiver.rcv_buf_acknum = rdp_sender.receiver_acknum
                
                print("acknum after rcv ack ack only case: ", rdp_receiver.rcv_buf_acknum)
                # rdp_receiver.rcv_buf_acknum += 1
                rdp_receiver.sequence_num = rdp_sender.snd_seq_num
                if (isfinacked == True):
                    print("fin was acked in a packet with only ack. good to close.")
                    rdp_receiver.state = "closed"

            elif("ACK" in packet.command):
                # ack with other stuff
                # deal with any state changes required
                print("acknum before rcv ack ack and else case: ", rdp_receiver.rcv_buf_acknum)
                rdp_sender.receiver_acknum = rdp_receiver.rcv_buf_acknum
                isfinacked = rdp_sender.rcv_ack(packet)
                rdp_receiver.rcv_buf_acknum = rdp_sender.receiver_acknum
                print("acknum after rcv ack ack and else case: ", rdp_receiver.rcv_buf_acknum)
                
                rdp_receiver.sequence_num = rdp_sender.snd_seq_num
                print("handling data/syn/etc receiver packet")
                response = rdp_receiver.rcv_data(packet)
                rdp_sender.receiver_acknum = rdp_receiver.rcv_buf_acknum
                print("acknum after rcv data ack and else case: ", rdp_receiver.rcv_buf_acknum)
                # rdp_receiver.rcv_buf_acknum += len(packet.payload)
                rdp_sender.receiver_acknum = rdp_receiver.rcv_buf_acknum
                rdp_sender.receiver_cur_window = rdp_receiver.rcv_buf_window
                rdp_sender.state = rdp_receiver.state

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
                rdp_sender.snd_seq_num = response.sequence + len(response.payload)
                rdp_receiver.sequence_num = rdp_sender.snd_seq_num
                rdp_sender.snd_buf.put(send_packet)
                print("\n Final sendpacket: ", send_packet, "\n")

            else:
                # no ack present, only other stuff
                print("handling data/syn/etc receiver packet")
                print("acknum before rcv dat no ack case: ", rdp_receiver.rcv_buf_acknum)
                response = rdp_receiver.rcv_data(packet)
                rdp_sender.receiver_acknum = rdp_receiver.rcv_buf_acknum
                print("acknum after rcv dat no ack case: ", rdp_receiver.rcv_buf_acknum)
                # rdp_receiver.rcv_buf_acknum += len(packet.payload) #WE ONLY INCREMENT ACK NUM IF VALID IN ORDER!
                rdp_sender.receiver_acknum = rdp_receiver.rcv_buf_acknum
                rdp_sender.receiver_cur_window = rdp_receiver.rcv_buf_window
                rdp_sender.state = rdp_receiver.state

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
                        
                    send_packet = response.commands + "\nSequence: " + str(rdp_sender.snd_seq_num) + "\nAcknowledgment: " + str(response.acknowledgment)
                    send_packet +="\nLength: " + str(len(response.payload)) + "\nWindow: " + str(response.window)
                    send_packet += "\n\n"
                    # encode just the headers string and concat the binary (dont encode). diff encodings is fine? regex later
                    send_packet = send_packet.encode()
                    send_packet += response.payload
                    print("response payload: ", response.payload)
                    rdp_sender.snd_seq_num = response.sequence + len(response.payload)
                    rdp_receiver.sequence_num = rdp_sender.snd_seq_num
                    rdp_sender.snd_buf.put(send_packet)
                    print("\n Final sendpacket: ", send_packet, "\n")


                else: print("packet response returned None...") #was handled in the receiver.
                # only case handled by sender - all else is figured out in receiver "data"
                rdp_sender.ack_num_rcvd = packet.acknowledgment
                # response = rdp_sender.rcv_ack(packet)
                
            
            if ("FIN" in packet.command and response != None and "ACK" in response.commands):
                # we received a fin, and our response was to ack it, so other sides sender is done.
                clientdonesending = True
                
                
                
                


            




            # if rdp_receiver.finrecv == True and rdp_sender.finsent == True:
            #     # all info sent. send fin from this side as havent yet
            #     rdp_sender.close()

    if ((udp_sock in writable) ):
        # In our case, socket will almost always be writable.

        for client in list(clientslist):
            rdp_sender = clientslist[client][0] # update sender and receiver to apply to current client only. 
            rdp_receiver = clientslist[client][1]

            print("client for loop in writable receiver ack num: ", rdp_receiver.rcv_buf_acknum)

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
                bytes_sent = udp_sock.sendto(unprocessed_packet, rdp_sender.client_address)
                # add packet to the unack list for error control
                if (packet.command != "ACK"):
                    print("\nadding packet to unack_packets\n")
                    # dont store plain ack packets for timeout.
                    rdp_sender.unack_packets[packet.sequence] = [packet, time.time()*1000] #store time for timeout check(ms)
                rdp_sender.most_recent_sent_seq = packet.sequence
                # remove the bytes already sent from snd_buf
                # THIS MIGHT BE BUGGY AS **** BECAUSE IDK WHAT DAMN DATATYPE TO USE OR THE FORMAT WITHIN IT.
                
                # rdp_sender.snd_buf = rdp_sender.snd_buf[bytes_sent:]


            if((rdp_receiver.state == "open" or rdp_receiver.state == "fin_recv") and rdp_sender.cansend == True):
                # only send things if either we are open, or if we are dealing with a syn-ack combo.

                # check if any data left to be sent.
                while (rdp_sender.known_window >= 1024 and len(rdp_receiver.responses_to_client) > 0):
                    # while we know we have more space to send stuff (and more stuff), line up more stuff to send (if exists).
                    # prepare basic response values
                    response = ack_response()
                    response.commands = ""
                    response.acknowledgment = -1
                    response.window = rdp_receiver.rcv_buf_window
                    response.sequence = rdp_sender.snd_seq_num 
                    response = rdp_receiver.grabdata(response)
                    if(len(rdp_receiver.responses_to_client) == 0):
                        # No more stuff to send. we can close the client 
                        rdp_receiver.state = "fin_sent"
                        rdp_sender.state = "fin_sent"
                    if len(response.payload) > 0:
                        # we have more data to send.
                        send_packet = response.commands + "\nSequence: " + str(rdp_sender.snd_seq_num) + "\nAcknowledgment: " + str(rdp_receiver.rcv_buf_acknum)
                        send_packet +="\nLength: " + str(len(response.payload)) + "\nWindow: " + str(rdp_receiver.rcv_buf_window) + "\n\n"
                        send_packet_binary = b"" + send_packet.encode()
                        send_packet_binary += response.payload
                        rdp_sender.snd_seq_num += len(response.payload)
                        rdp_receiver.sequence_num = rdp_sender.snd_seq_num
                        rdp_sender.snd_buf.put(send_packet_binary)


                


            # WILLL NEED LOGIC FOR WHEN BOTH OPEN WHERE WE ADD DATA IN RDP_RECEIVER!!!!!!!!!!!!!!!!!!!!!
            # if(rdp_sender.state == "open" and rdp_receiver.state == "open"):
            #     # only send things if both sides are open
            #     # file_data = b""
            #     while (rdp_sender.known_window >= 1024):
            #         # while we know we have more space to send stuff, line up more stuff to send (if exists). 
            #         # file_data = requested_file.read(1024)
            #         # file_data = file_data.decode()
            #         if(current_byte + 1024 <= totalbytes):
            #             # 1024 bytes or more left to read
            #             file_data = requested_file_binary[current_byte:(current_byte+1024)]
            #             current_byte += 1024
            #         elif(current_byte < totalbytes):
            #             # less than 1024 bytes to read... watch out for inclusivity here!
            #             file_data = requested_file_binary[current_byte : totalbytes]
            #             # update current byte to be more than total
            #             current_byte += totalbytes
            #         else:
            #             # no more bytes to read
            #             file_data = b""
                    
            #         if ((file_data != b"")):
            #             # pull more data from the file, and prepare the packet to send. 
            #             # file_data = requested_file.read(1024)
            #             send_packet = "DAT\nSequence: " + str(rdp_sender.snd_seq_num) + "\nLength: " + str(len(file_data))
            #             send_packet += "\n\n"
            #             # encode just the headers string and concat the binary (dont encode). diff encodings is fine? regex later
            #             send_packet = send_packet.encode()
            #             send_packet += file_data

            #             rdp_sender.snd_buf.put(send_packet)

            #             # update own sequence number based on the data sent.
            #             rdp_sender.snd_seq_num = rdp_sender.snd_seq_num + len(file_data)
            #             # subtract the used space from the known window.
            #             rdp_sender.known_window -= len(file_data)


            #         elif((file_data == b"") and rdp_sender.state == "open"):
            #             # request to close the connection since work is done, and not waiting on space.
            #             if ((rdp_sender.snd_seq_num == rdp_sender.ack_num_rcvd) and (rdp_sender.state)):
            #                 rdp_sender.close()
            #                 break
            #             else:
            #                 # break to prevent blocking wait
            #                 break
            #         else:
            #             # means waiting on window, or waiting on close ack, so dont do anything
            #             break
                # after while, no more space to send (from beginning or after adding more data)
                # rdp_sender.check_timeout()
    


            # TODO THIS NEEDS TO BE CHANGED TO ADD REQUESTS TO BUFFER AND MAYBE MOVED TO WHERE CURRENTLY OCCURING.
            # # check for any data to write to file
            # window_before_write = rdp_receiver.rcv_buf_window
            # while (not rdp_receiver.rcv_final_buf.empty()):
            #     # while there is still data that has been sorted and ready to write...
            #     try:
            #         data = rdp_receiver.rcv_final_buf.get_nowait()
            #         # rdp_receiver.rcv_buf_window += len(data)
            #     except queue.Empty:
            #         # should not occur...
            #         pass
            #     file_to_write.write(data)
        
            # window_after_write = rdp_receiver.rcv_buf_window
            # if (window_after_write - window_before_write >= (rdp_receiver.rcv_buf_window_max / 2)):
            #     # if more than half of the window has been restored, send as new message. 
            #     pass
            
            
            rdp_sender.synsent = rdp_receiver.synsent
            rdp_sender.check_timeout()
            print("\nmain loop states. Sender: ", rdp_sender.state, " Receiver: ", rdp_receiver.state, "\n")
            print("*** client closer values (states above). clientdonesending: ", clientdonesending, " rdpsender.donesending: ", rdp_sender.donesending)
            if ((rdp_sender.state == "closed" and rdp_receiver.state == "closed") or (clientdonesending and rdp_sender.donesending)):
                # both sides are done. remove sender and receiver. 
                rdp_sender.state = "closed"
                rdp_receiver.state = "closed"
                print("removing client from clientslist")
                del clientslist[client]
                # time.sleep(0.5)

# after this, both sides are closed once again. 
# close files. THIS SHOULD BE DONE RIGHT AFTER OPENING THE FILES AND STORING WITHIN APPROPREATE CLASS. 
requested_file.close()
file_to_write.close()


# FOR TESTING ONLY ///////////////////////////////////////////////
# import os
# import filecmp
# print("file comparison result... Are files the same? ", filecmp.cmp(read_file_name, write_file_name))
# cmpstring = "cmp -b " + read_file_name + " " + write_file_name
# print("cmp output if difference exists: ")
# os.system(cmpstring)
# print("failcount: ", rdp_sender.failcount)
# DELETE BEFORE HANDIN!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

