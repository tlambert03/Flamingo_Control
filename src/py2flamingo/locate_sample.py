# TO DO? heavy use of workflow files could probably be reduced to logging, with dictionaries being sent instead.
# TO DO? Modify to handle other types of workflows than Zstacks
# HARDCODED plane spacing and framerate


import copy
import shutil
import time
from global_objects import clear_all_events_queues
import functions.calculations
from functions.microscope_connect import *
from functions.text_file_parsing import *

plane_spacing = 10
framerate = 40.0032  # /s


def locate_sample(
    connection_data: list,
    xyzr_init: list,
    visualize_event,
    other_data_queue,
    image_queue,
    command_queue,
    z_plane_queue,
    intensity_queue,
    system_idle: Event,
    processing_event,
    send_event,
    terminate_event,
    command_data_queue,
    stage_location_queue,
    laser_channel="Laser 3 488 nm",
    laser_setting="5.00 1",
    z_search_depth=2.0,
    data_storage_location=os.path.join("/media", "deploy", "MSN_LS"),
):
    """
    Main command/control thread for LOCATING AND IF SAMPLE. Takes in some hard coded values which could potentially be handled through a GUI.
    Goes to the tip of the sample holder, then proceeds downward taking MIPs to find the sample.
    Currently uses a provided IF channel to find a maxima, but it might be possible to use brightfield LEDs to find a minima.
    TO DO: handle different magnifications, search ranges

    WiFi warning: image data transfer will be very slow over wireless networks - use hardwired connections
    """
    #in case of second run, clear out any remaining data or flags.
    terminate_event.clear() 
    clear_all_events_queues()
    # Look in the functions/command_list.txt file for other command codes, or add more
    commands = text_to_dict(
        os.path.join("src", "py2flamingo", "functions", "command_list.txt")
    )

    # Testing fidelity
    # print(commands)
    # dict_to_text('functions/command_test.txt', commands)

    COMMAND_CODES_COMMON_SCOPE_SETTINGS_LOAD = int(
        commands["CommandCodes.h"]["COMMAND_CODES_COMMON_SCOPE_SETTINGS_LOAD"]
    )
    # COMMAND_CODES_COMMON_SCOPE_SETTINGS  = int(commands['CommandCodes.h']['COMMAND_CODES_COMMON_SCOPE_SETTINGS'])
    COMMAND_CODES_CAMERA_WORK_FLOW_START = int(
        commands["CommandCodes.h"]["COMMAND_CODES_CAMERA_WORK_FLOW_START"]
    )
    COMMAND_CODES_STAGE_POSITION_SET = int(
        commands["CommandCodes.h"]["COMMAND_CODES_STAGE_POSITION_SET"]
    )
    # COMMAND_CODES_SYSTEM_STATE_IDLE  = int(commands['CommandCodes.h']['COMMAND_CODES_SYSTEM_STATE_IDLE'])
    COMMAND_CODES_CAMERA_PIXEL_FIELD_Of_VIEW_GET = int(
        commands["CommandCodes.h"]["COMMAND_CODES_CAMERA_PIXEL_FIELD_Of_VIEW_GET"]
    )
    COMMAND_CODES_CAMERA_IMAGE_SIZE_GET = int(
        commands["CommandCodes.h"]["COMMAND_CODES_CAMERA_IMAGE_SIZE_GET"]
    )
    ##############################

    ##
    # Queues and Events for keeping track of what state the software/hardware is in
    # and pass information between threads (Queues)
    ##

    nuc_client, live_client, wf_zstack, LED_on, LED_off = connection_data
    image_pixel_size, scope_settings = get_microscope_settings(
        command_queue, other_data_queue, send_event
    )
    command_queue.put(COMMAND_CODES_CAMERA_IMAGE_SIZE_GET)
    send_event.set()
    time.sleep(0.1)

    frame_size = other_data_queue.get()
    FOV = image_pixel_size * frame_size
    # Currently a 1.3 modifier hardcoded since all samples in use are larger than a field of view
    # This makes the search faster and is unlikely to miss the sample.
    # pixel_size*frame_size #pixel size in mm*number of pixels per frame
    y_move = FOV * 1.3 
    print(f"y_move search step size is currently {y_move}mm")
    ############
    ymax = float(scope_settings["Stage limits"]["Soft limit max y-axis"])
    print(f"ymax is {ymax}")
    ###############

    go_to_XYZR(command_data_queue, command_queue, send_event, xyzr_init)
    ####################

    # Brightfield image to verify sample holder location
    snap_dict = workflow_to_dict(os.path.join("workflows", wf_zstack))
    snap_dict = dict_to_snap(snap_dict, xyzr_init, framerate, plane_spacing)
    snap_dict = laser_or_LED(snap_dict, laser_channel, laser_setting, laser_on=False)

    dict_to_workflow(os.path.join("workflows", "currentSnapshot.txt"), snap_dict)

    # WORKFLOW.TXT FILE IS ALWAYS USED FOR send_event, other workflow files are backups and only used to validate steps
    shutil.copy(
        os.path.join("workflows", "currentSnapshot.txt"),
        os.path.join("workflows", "workflow.txt"),
    )

    # take a snapshot
    print("Acquire a brightfield snapshot")
    command_queue.put(COMMAND_CODES_CAMERA_WORK_FLOW_START)
    send_event.set()

    while not system_idle.is_set():
        time.sleep(0.1)
    # Possibly make this a mini function
    stage_location_queue.put(xyzr_init)
    visualize_event.set()

    # Clear out collected data
    processing_event.set()
    # clear the data out of the data queues
    top25_percentile_mean = intensity_queue.get()

    # Move half of a frame down from the current position
    ######how to determine half of a frame generically?######

    # images = []
    coords = []
    # initialize the active coordinates: starting Z position is treated as the middle of the search depth
    z_init = xyzr_init[2]
    zstart = float(z_init) - float(z_search_depth) / 2
    zend = float(z_init) + float(z_search_depth) / 2
    xyzr = [xyzr_init[0], xyzr_init[1], zstart, xyzr_init[3]]

    # Settings for the Z-stacks, assuming an IF search
    wf_dict = workflow_to_dict(os.path.join("workflows", wf_zstack))
    wf_dict = laser_or_LED(wf_dict, laser_channel, laser_setting, LED_off, LED_on, True)
    wf_dict["Experiment Settings"]["Save image drive"] = data_storage_location
    wf_dict["Experiment Settings"]["Save image directory"] = "Sample Search"
    wf_dict = dict_comment(wf_dict, "Delete")
    ####################HARDCODE WARNING#
    wf_dict = calculate_zplanes(wf_dict, z_search_depth, framerate, plane_spacing)

    ##############################################################################
    # Loop through a set of Y positions (increasing is 'lower' on the sample)
    # check for a terminated thread or that the search range has gone 'too far' which is instrument dependent
    # Get a max intensity projection at each Y and look for a peak that could represent the sample
    # Sending the MIP reduces the amount of data sent across the network, minimizing total time
    # Store the position of the peak and then go back to that stack and try to find the focus
    i = 0
    # xyzr_init[1] is the initial y position
    while not terminate_event.is_set() and (float(xyzr_init[1]) + y_move * i) < ymax:
        print("Starting Y axis search " + str(i + 1))
        print("*")
        # adjust the Zstack position based on the last snapshot Z position

        # All adjustments are performed on the wf_dict,
        wf_dict = dict_positions(wf_dict, xyzr, zend)

        # Write a new workflow based on new Y positions
        dict_to_workflow(os.path.join("workflows", "current" + wf_zstack), wf_dict)
        dict_to_text(os.path.join("workflows", "current_test_" + wf_zstack), wf_dict)
        # Additional step for records that nothing went wrong if swapping between snapshots and Zstacks

        shutil.copy(
            os.path.join("workflows", "current" + wf_zstack),
            os.path.join("workflows", "workflow.txt"),
        )
        print(f"coordinates x: {xyzr[0]}, y: {xyzr[1]}, z:{xyzr[2]}, r:{xyzr[3]}")

        # print('before acquire Z'+ str(i+1))
        command_queue.put(COMMAND_CODES_CAMERA_WORK_FLOW_START)
        send_event.set()
        visualize_event.set()
        while not system_idle.is_set():
            time.sleep(0.1)

        stage_location_queue.put(xyzr)

        # print('after acquire Z'+ str(i+1))
        # print('processing set')
        processing_event.set()
        top25_percentile_mean = intensity_queue.get()
        # print(f'intensity sum is {intensity}')
        # Store data about IF signal at current in focus location
        coords.append([copy.deepcopy(xyzr), top25_percentile_mean])

        # Loop may finish early if drastic maxima in intensity sum is detected

        top25_percentile_means = [coord[1] for coord in coords]
        print(f"Intensity means: {top25_percentile_means}")
        if maxima := functions.calculations.check_maxima(top25_percentile_means):
            break
        # move the stage up
        xyzr[1] = float(xyzr[1]) + y_move
        i = i + 1
    # Check for cancellation from GUI

    if terminate_event.is_set():
        print("Find Sample terminating")
        terminate_event.clear()
        return

    xyzr = coords[maxima][0]
    x, y, z, r = coords[maxima][0]
    print(f"Sample located at x: {x}, y: {y}, r:{r}")
    print("Finding focus in Z.")

    # Not really necessary as the workflow will handle this.
    # mostly a demonstration of using the go_to_XYZR function
    go_to_XYZR(command_data_queue, command_queue, send_event, xyzr)

    # Wireless is too slow and the nuc buffer is only 10 images, which can lead to overflow and deletion before the local computer pulls the data
    # for Z stacks larger than 10, make sure to split them into 10 image components and wait for each to complete.
    total_number_of_planes = float(wf_dict["Stack Settings"]["Number of planes"])

    # number of image planes the nuc can/will hold in its buffer before overwriting
    # check with Joe Li before increasing this above 10. Decreasing it below 10 is fine.
    buffer_max = 10
    ###################################################################################
    # loop through the total number of planes, 10 planes at a time
    loops = int(total_number_of_planes / buffer_max + 0.5)
    step_size_mm = float(wf_dict["Experiment Settings"]["Plane spacing (um)"]) / 1000
    z_search_depth = step_size_mm * buffer_max
    wf_dict = calculate_zplanes(wf_dict, z_search_depth, framerate, plane_spacing)
    # wf_dict['Stack Settings']['Number of planes'] = buffer_max
    # combined_stack = []
    ###
    ##
    # NEED STOP EARLY CONDITION
    ###
    coordsZ = []
    i = 0
    for i in range(loops):
        print(f"Subset of planes acquisition {i} of {loops}")
        # Check for cancellation from GUI
        if terminate_event.is_set():
            print("Find Sample terminating")
            terminate_event.clear()
            return
        # calculate the next step of the Z stack and apply that to the workflow file
        xyzr[2] = float(z) - float(z_search_depth) / 2 + i * buffer_max * step_size_mm
        zEnd = (
            float(z) - float(z_search_depth) / 2 + (i + 1) * buffer_max * step_size_mm
        )
        dict_positions(wf_dict, xyzr, zEnd, save_with_data=False, get_zstack=False)

        dict_to_workflow(os.path.join("workflows", "current" + wf_zstack), wf_dict)

        shutil.copy(
            os.path.join("workflows", "current" + wf_zstack),
            os.path.join("workflows", "workflow.txt"),
        )
        print(
            f"start: {wf_dict['Start Position']['Z (mm)']}, end: {wf_dict['End Position']['Z (mm)']}"
        )
        command_queue.put(COMMAND_CODES_CAMERA_WORK_FLOW_START)
        send_event.set()
        visualize_event.set()
        while not system_idle.is_set():
            time.sleep(0.1)
        stage_location_queue.put(xyzr)

        # print('after acquire Z'+ str(i+1))
        # print('processing set')
        processing_event.set()
        top25_percentile_mean = intensity_queue.get()
        coordsZ.append([copy.deepcopy(xyzr), top25_percentile_mean])
        top25_percentile_means = [coord[1] for coord in coordsZ]

        print(f"Intensity means: {top25_percentile_means}")
        if maxima := functions.calculations.check_maxima(top25_percentile_means):
            break


    xyzr = coordsZ[maxima][0]
    x = coordsZ[maxima][0][0]
    y = coordsZ[maxima][0][1]
    queue_z = coordsZ[maxima][0][2]
    r = coordsZ[maxima][0][3]
    print("z focus plane " + str(queue_z))

    # calculate the Z position for that slice

    # step = float(wf_dict['Experiment Settings']['Plane spacing (um)'])*0.001 #convert to mm
    # Find the Z location for the snapshot, starting from the lowest value in the Z search range
    # 0.5 is subtracted from 'queue_z' to find the middle of one of the MIPs, which is made up of 'buffer_max' individual 'step's
    zSnap = float(queue_z) - 0.5 * step_size_mm
    ######################
    print(f"Object located at {zSnap}")

    # XYR should all be correct already
    # Move to correct Z position, command 24580
    command_data_queue.put([3, 0, 0, zSnap])

    command_queue.put(COMMAND_CODES_STAGE_POSITION_SET)  # movement
    send_event.set()
    while not command_queue.empty():
        time.sleep(0.1)

    # Take a snapshot there using the user defined laser and power

    ##############
    snap_dict = wf_dict
    xyzr[2] = zSnap
    print(f'final xyzr snap {xyzr}')
    snap_dict["Experiment Settings"]["Save image directory"] = "Sample"
    snap_dict = dict_comment(snap_dict, "Sample located")

    snap_dict = dict_to_snap(snap_dict, xyzr, framerate, plane_spacing)
    snap_dict = laser_or_LED(snap_dict, laser_channel, laser_setting, laser_on=True)
    dict_to_workflow(os.path.join("workflows", "current" + wf_zstack), snap_dict)
    shutil.copy(
        os.path.join("workflows", "current" + wf_zstack),
        os.path.join("workflows", "workflow.txt"),
    )
    command_queue.put(COMMAND_CODES_CAMERA_WORK_FLOW_START)
    send_event.set()
    stage_location_queue.put(xyzr)
    visualize_event.set()
    while not system_idle.is_set():
        time.sleep(0.1)
    # only close out the connections once the final image is collected

    image_queue.get()
    # Clean up 'delete' PNG files or dont make them
    ###
