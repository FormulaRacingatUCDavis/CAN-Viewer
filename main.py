#!/usr/bin/env python3

# 12/3/2023: Scrolling view: anything new needs to populate the top of the list. push all the old stuff down. look at the redraw 

# based on alexandreblin's CAN monitor

import argparse
import curses
import sys
import threading
import traceback
import time
from datetime import datetime
from handler import InvalidFrame, SerialHandler


should_redraw = threading.Event()
stop_reading = threading.Event()

can_messages = {}
can_message_counts = {}
can_messages_lock = threading.Lock()

frameIDArray = []
dataArray = []
timeArray = []



# for highlighting
class Colors:
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    END = '\033[0m'
def highlight_message(message, color):
    highlighted_message = f"{color}{message}{Colors.END}"
    print(highlighted_message)

thread_exception = None

view_mode = 'scroll'
# mode static or scroll 

def reading_loop(source_handler, whitelist):
    """Background thread for reading."""
    try:
        while not stop_reading.is_set():
            try:
                frame_id, data = source_handler.get_message()
                frameIDArray.append(frame_id) ; dataArray.append(data) ; timeArray.append(datetime.now().isoformat(timespec='milliseconds')[14:])

            except InvalidFrame:
                continue
            except EOFError:
                break

            if len(whitelist) > 0 and frame_id not in whitelist:
                continue

            # Add the frame to the can_messages dict and tell the main thread to refresh its content
            with can_messages_lock:
                can_messages[frame_id] = data

                # Update message count
                if frame_id in can_message_counts.keys():
                    can_message_counts[frame_id] += 1
                else:
                    can_message_counts[frame_id] = 1

                should_redraw.set()

        stop_reading.wait()

    except:
        if not stop_reading.is_set():
            # Only log exception if we were not going to stop the thread
            # When quitting, the main thread calls close() on the serial device
            # and read() may throw an exception. We don't want to display it as
            # we're stopping the script anyway
            global thread_exception
            thread_exception = sys.exc_info()


def init_window(stdscr):
    """Init a window filling the entire screen with a border around it."""
    stdscr.clear()
    stdscr.refresh()

    max_y, max_x = stdscr.getmaxyx()
    root_window = stdscr.derwin(max_y, max_x, 0, 0)

    root_window.box()

    return root_window


def format_data_hex(data):
    """Convert the bytes array to an hex representation."""
    # Bytes are separated by spaces.
    return ' '.join('%02X' % byte for byte in data)


# def format_data_ascii(data):
#     """Try to make an ASCII representation of the bytes.

#     Non printable characters are replaced by '?' except null character which
#     is replaced by '.'.
#     """
#     msg_str = ''
#     for byte in data:
#         char = chr(byte)
#         if char == '\0':
#             msg_str = msg_str + '.'
#         elif ord(char) < 32 or ord(char) > 126:
#             msg_str = msg_str + '?'
#         else:
#             msg_str = msg_str + char
#     return msg_str


highlighted = ['0x18']
def scrollView(reading_thread):
    currentIndex = 0

    while view_mode == 'scroll':
        if len(dataArray) > 0 and len(frameIDArray) > 0:
            with can_messages_lock:
                while (currentIndex < len(dataArray)):
                    formattedMsg = f'{timeArray[currentIndex]} 0x{frameIDArray[currentIndex]:0X}'.ljust(20) + format_data_hex(dataArray[currentIndex])

                    # the l just adjust the spacing between the id and bytes
                    if f'0x{frameIDArray[currentIndex]:0x}' in highlighted:
                        highlight_message(formattedMsg, Colors.BLUE)
                    else:
                        print(formattedMsg)
                    currentIndex += 1


    currentIndex = 0
    while view_mode == 'scroll':
        if len(dataArray) > 0 and len(frameIDArray) > 0:
            with can_messages_lock:
                while (currentIndex < len(dataArray)):
                    print(format_data_hex(dataArray[currentIndex]))
                    currentIndex += 1
                
def main(stdscr, reading_thread):               
    if view_mode != 'scroll':
        global scrollOffset
        scrollOffset = 0
        """Main function displaying the UI."""
        # Don't print typed character
        curses.noecho()
        curses.cbreak()
        curses.curs_set(0) # set cursor state to invisible

        # Set getch() to non-blocking
        stdscr.nodelay(True)

        win = init_window(stdscr)

        while True:
            # should_redraw is set by the serial thread when new data is available
            if view_mode == 'static' and should_redraw.wait(timeout=0.05):  # Timeout needed in order to react to user input
                max_y, max_x = win.getmaxyx()

                column_width = 50
                id_column_start = 2
                bytes_column_start = 13
                text_column_start = 38

                # Compute row/column counts according to the window size and borders
                row_start = 4
                lines_per_column = max_y - (1 + row_start)
                num_columns = (max_x - 2) // column_width
        
                # Setting up column headers
                for i in range(0, num_columns):
                    win.addstr(1, id_column_start + i * column_width, 'ID')
                    win.addstr(1, bytes_column_start + i * column_width, 'Bytes')
                    win.addstr(1, text_column_start + i * column_width, 'Count')

                row = row_start  # The first column starts a bit lower to make space for the 'press q to quit message'
                current_column = 0
            
                c = stdscr.getch()
                if c == ord('q') or not reading_thread.is_alive():
                    break
                # Control scrollOffset for static scrolling ; 'u' = up , 'd' = down 
                elif c == ord('d'):
                    scrollOffset = min(scrollOffset + 1, len(can_messages) - 2)
                    should_redraw.set()
                elif c == ord('u'):
                    scrollOffset = max(scrollOffset + 1, 0)
                    should_redraw.set()
                elif c == curses.KEY_RESIZE:
                    win = init_window(stdscr)
                    should_redraw.set()

                # Make sure we don't read the can_messages dict while it's being written to in the reading thread
                with can_messages_lock:
                    # for static scrolling
                    frame_id = list(can_messages.keys())

                    visible_id = frame_id[scrollOffset:scrollOffset + 2]
                    # second index determines the amount of messages that are visible 
                
                    for message_id in visible_id:
                        msg = can_messages[message_id]

                        msg_bytes = format_data_hex(msg)

                        # print ID in hex
                        win.addstr(row, id_column_start + current_column * column_width, '0x%X'.ljust(5) % message_id)
                        # win.addstr(row, id_column_start + 5 + current_column * column_width, '%s' % str(frame_id).ljust(5)) 

                        # print bytes
                        win.addstr(row, bytes_column_start + current_column * column_width, msg_bytes.ljust(23))

                        # print count
                        win.addstr(row, text_column_start + current_column * column_width, (str)(can_message_counts[message_id]).ljust(8))

                        row = row + 1

                        if row >= lines_per_column + row_start:
                            # column full, switch to the next one
                            row = row_start
                            current_column = current_column + 1

                            if current_column >= num_columns:
                                break

                win.refresh()

                should_redraw.clear()


def parse_ints(string_list):
    int_set = set()
    for line in string_list:
        try:
            int_set.add(int(line, 0))
        except ValueError:
            continue
    return int_set

def parse_strs(string_list):
	# temporary string parsing. Probably needs to be improved or fixed in some way but idk.
	str_set = set()
	for line in string_list:
		for string in line.strip().split():
			str_set.add(string)
	return str_set


def run():
	parser = argparse.ArgumentParser(description='Process CAN data from a serial device or from a file.')
	parser.add_argument('serial_device', type=str, nargs='?')
	parser.add_argument('baud_rate', type=int, default=115200, nargs='?',
						help='Serial baud rate in bps (default: 115200)')
	parser.add_argument('--whitelist', '-w', nargs='+', metavar='WHITELIST', help="IDs accepted")
	parser.add_argument('--whitelist-file','-wf',metavar='WHITELIST_FILE', help="File containing ids that are accepted")
	parser.add_argument('--view', '-v', metavar='VIEW', help="View mode - static or scroll")
	# capital H in --Highlight and -H because -h conflicts
	parser.add_argument('--Highlight', '-H', nargs='+', metavar='HIGHLIGHT', help="IDs to highlight")
	parser.add_argument('--Highlight-file','-Hf',metavar='HIGHLIGHT_FILE', help="File containing ids to highlight")
	args = parser.parse_args()

	# checks arguments
	if args.serial_device:
		source_handler = SerialHandler(args.serial_device, baudrate=args.baud_rate)
	else:
		print("Please specify serial device")
		print()
		parser.print_help()
		return

	# --whitelist-file prevails over --whitelist
	if args.whitelist_file:
		with open(args.whitelist_file) as f_obj:
			whitelist = parse_ints(f_obj)
	elif args.whitelist:
		whitelist = parse_ints(args.whitelist)
	else:
		whitelist = set()

	if args.Highlight_file:
		global highlighted
		with open(args.Highlight_file) as f_obj:
			highlighted = parse_strs(f_obj)
	elif args.Highlight:
		highlighted = args.Highlight
	else:
		highlighted = set()

	if args.view:
		global view_mode
		view_mode = str(args.view)

	reading_thread = None

	try:
		# If reading from a serial device, it will be opened with timeout=0 (non-blocking read())
		source_handler.open()

		# Start the reading background thread
		reading_thread = threading.Thread(target=reading_loop, args=(source_handler, whitelist,))
		reading_thread.start()

		# Make sure to draw the UI the first time even if no data has been read (commented out to test scroll 1/13/2023)
		#should_redraw.set()

		# Start the main loop
		scrollView(reading_thread=threading.Thread(target=reading_loop, args=(source_handler, whitelist,)))
		curses.wrapper(main, reading_thread)
	finally:
		# Cleanly stop reading thread before exiting
		if reading_thread:
			stop_reading.set()

			if source_handler:
				source_handler.close()

			reading_thread.join()

			# If the thread returned an exception, print it
			if thread_exception:
				traceback.print_exception(*thread_exception)
				sys.stderr.flush()

if __name__ == '__main__':
	run()