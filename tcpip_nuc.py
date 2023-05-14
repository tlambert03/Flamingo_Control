import socket
import os
#import sys
#import time
import numpy as np
#import select
import struct

NUC_IP = '10.129.37.17' #From Connection tab in GUI
PORT_NUC = 53717 #From Connection tab in GUI

#This used to be one function instead of two and could still go back. It was easier to understand as two, for me.
def wf_to_nuc(client, wf_file, command):


    '''

    function to send a workflow file to nuc and start the workflow

    :param FLAMINGO_IP: ip address of NUC

    :param FLAMINGO_PORT: Port 53717

    :param wf_file: path to workflow file

    :param command: 4136 to start a workflow (microscope control software verison dependent)

    :param wf: whether a workflow file is sent of not

    :return: nothing

    '''

    #print(f"workflow command is {command}")
    fileBytes = os.path.getsize(wf_file)
    #print(fileBytes)

    cmd_start = np.uint32(0xF321E654)  # start command

    cmd = np.uint32(command) #cmd command (CommandCodes.h): open in Visual Studio Code + install C/C++ Extension IntelliSense, when hovering over command binary number visible

    status = np.int32(0)

    hardwareID = np.int32(0)

    subsystemID = np.int32(0)

    clientID = np.int32(0)

    int32Data0 = np.int32(0) #e.g. for stage movement: 1 == x-axis, 2 == y.axis, 3 == z.axis, 4 = rotational axis

    int32Data1 = np.int32(0)

    int32Data2 = np.int32(0)

    cmdDataBits0 = np.int32(0)

    doubleData = float(0) #e.g. 64-bits, values of the end-position of the axis

    addDataBytes = np.int32(fileBytes) # only if you sent a workflow file, else fileBytes = 0

    buffer_72 = b'\0' * 72

    cmd_end = np.uint32(0xFEDC4321)  # end command



    s = struct.Struct('I I I I I I I I I I d I 72s I') # pack everything to binary via struct

    scmd = s.pack(cmd_start, cmd, status, hardwareID,

                  subsystemID, clientID, int32Data0,

                  int32Data1, int32Data2, cmdDataBits0,

                  doubleData, addDataBytes, buffer_72, cmd_end)

    try:
        #print(command)

        #print(wf_file)
        workflow_file = open(wf_file).read()
        #print('sending')
        client.send(scmd)
        #print(len(scmd))
        client.send(workflow_file.encode())
        print('Workflow file sent')

        return
        #addData = client.recv(received[11]) # unpack additional data sent by the nuc

    except socket.error:

        print('Failed to send data wf')

#Commands to nuc, requires additional input values, data#, and does not require a workflow file
def command_to_nuc(client,command, data0=0, data1=0, data2=0, value=0.0):

    '''

    function to send a workflow file to nuc and start the workflow

    :param FLAMINGO_IP: ip address of NUC

    :param FLAMINGO_PORT: Port 53717

    :param wf_file: path to workflow file

    :param command: 4136 to start a workflow (microscope control software verison dependent)

    :param wf: whether a workflow file is sent of not

    :return: nothing

    '''

    cmd_start = np.uint32(0xF321E654)  # start command

    cmd = np.uint32(command) #cmd command (CommandCodes.h): open in Visual Studio Code + install C/C++ Extension IntelliSense, when hovering over command binary number visible

    status = np.int32(0)

    hardwareID = np.int32(0)

    subsystemID = np.int32(0)

    clientID = np.int32(0)

    int32Data0 = np.int32(data0) #e.g. for stage movement: 0 == x-axis, 1 == y.axis, 2 == z.axis, 3 = rotational axis

    int32Data1 = np.int32(data1)

    int32Data2 = np.int32(data2)

    cmdDataBits0 = np.int32(0)

    doubleData = float(value) #e.g. 64-bits, values of the end-position of the axis

    addDataBytes = np.int32(0) # only if you sent a workflow file, else fileBytes = 0

    buffer_72 = b'\0' * 72

    cmd_end = np.uint32(0xFEDC4321)  # end command



    s = struct.Struct('I I I I I I I I I I d I 72s I') # pack everything to binary via struct

    scmd = s.pack(cmd_start, cmd, status, hardwareID,

                  subsystemID, clientID, int32Data0,

                  int32Data1, int32Data2, cmdDataBits0,

                  doubleData, addDataBytes, buffer_72, cmd_end)


    #print('before try')
    try:
        client.send(scmd)
        return #received
    except socket.error as e:
        print('cmd to nuc - Failed to send data', e)

# replaced by idle_state
# def is_stage_stopped(client, c_StageStopCheck):
#     all_true = False
#     xb= yb= zb= rb = False
#     while not all_true:
#         if not xb:
#             xb = command_to_nuc(client, c_StageStopCheck, data0 = 0)[2] #second entry should be "status", with 0 indicating not finished
#         if not yb:
#             yb = command_to_nuc(client, c_StageStopCheck, data0 = 1)[2]
#         if not zb:
#             zb = command_to_nuc(client, c_StageStopCheck, data0 = 2)[2]
#         if not rb:
#             rb = command_to_nuc(client, c_StageStopCheck, data0 = 3)[2]
#         all_true = xb*yb*rb*zb #if any value isn't 1, all_true stays 0/False
#         time.sleep(0.5)
