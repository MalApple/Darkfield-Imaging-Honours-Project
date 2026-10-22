from tkinter import *
from tkinter import ttk
from tkinter import filedialog
from tkinter.scrolledtext import ScrolledText
from arduino_controller import ArduinoController

from saved_presets import load_presets, save_presets

import sys


# ARDUINO SETUP
def handle_arduino_message(message):
    print("Arduino:", message)
    if message.startswith("OK: homed"):
        root.after(0, on_homing_complete)



# Wrapping Widget
class WrappingLabel(Label):
    #Label that automatically wraps its text to fit the current widget width.
    def __init__(self, master=None, **kwargs):
        super().__init__(master, **kwargs)
        self.bind('<Configure>', self._on_resize)

    def _on_resize(self, event):
        if event.width != self.cget('wraplength'):
            self.config(wraplength=event.width)


# WINDOW SETUP
root = Tk()
root.title("Darkfield Imaging Interface")
#root.iconbitmap('images/seal.ico')
root.geometry('800x700')


# FRAMES
root.columnconfigure(0, weight=1, uniform='cols')
root.columnconfigure(1, weight=1, uniform='cols')

home_frame = Frame(root)
info_frame = LabelFrame(root)
oper_frame = LabelFrame(root)
input_frame = LabelFrame(root, text='Image Inputs')
analysis_frame = LabelFrame(root, text='Analysis')
console_frame = Frame(root)

# Frame configuration
oper_frame.columnconfigure(0, weight=1, uniform='btns')
oper_frame.columnconfigure(1, weight=1, uniform='btns')
info_frame.columnconfigure(0, weight=1)
info_frame.columnconfigure(1, weight=1)
info_frame.columnconfigure(2, weight=1, uniform='load_delete')
info_frame.columnconfigure(3, weight=1, uniform='load_delete')

root.rowconfigure(3, weight=1)

home_frame.grid(row=0, column=0, columnspan=2, sticky='ew')
info_frame.grid(row=1, column=0, sticky='nsew', padx=10, pady=5)
oper_frame.grid(row=1, column=1, sticky='nsew', padx=10, pady=5)
input_frame.grid(row=2, column=0, sticky='nsew', padx=10, pady=5)
analysis_frame.grid(row=2, column=1, sticky='nsew', padx=10, pady=5)
console_frame.grid(row=3, column=0, columnspan=2, sticky='nsew', padx=10, pady=(0, 10))


# HOME FRAME
home_status_label = Label(
    home_frame,
    text='Not homed — click Home before using any other control',
    font=("Helvetica", 11, 'bold'),
    fg='red'
)

def home_clicked():
    set_controls_enabled(False)
    home_button.config(state=DISABLED)
    home_status_label.config(text='Homing...', fg='orange')
    arduino.home()

def on_homing_complete():
    home_status_label.config(text='Homed', fg='green')
    home_button.config(state=NORMAL)
    set_controls_enabled(True)

home_button = Button(
    home_frame,
    text='Home',
    command=home_clicked,
    font=("Helvetica", 11, 'bold')
)

home_status_label.grid(row=0, column=0, sticky='w', padx=10, pady=10)
home_button.grid(row=0, column=1, sticky='e', padx=10, pady=10)
home_frame.columnconfigure(0, weight=1)


# CONSOLE FRAME
console_label = Label(console_frame, text='Console Output:', font=("Helvetica", 10))
console_text = ScrolledText(console_frame, height=8, state=DISABLED, font=("Consolas", 9))
console_label.pack(anchor='w')
console_text.pack(fill=BOTH, expand=True)

class ConsoleRedirector:
    """Mirrors writes to the real stdout AND appends them into console_text.
    write() can be called from a background thread (e.g. the Arduino's
    serial reader thread), so the actual widget update is marshalled onto
    the main thread via root.after."""
    def __init__(self, text_widget, original_stream):
        self.text_widget = text_widget
        self.original_stream = original_stream

    def write(self, message):
        self.original_stream.write(message)
        if message.strip():
            root.after(0, self._append, message)

    def _append(self, message):
        self.text_widget.config(state=NORMAL)
        self.text_widget.insert(END, message if message.endswith('\n') else message + '\n')
        self.text_widget.see(END)
        self.text_widget.config(state=DISABLED)

    def flush(self):
        self.original_stream.flush()

sys.stdout = ConsoleRedirector(console_text, sys.stdout)


# INFO FRAME
info_heading = WrappingLabel(info_frame, text='Screen Position Information', font=("Helvetica", 18), anchor='w')
info_heading.grid(row=0, column=0, columnspan=4, sticky='ew', padx=10)

instructions = WrappingLabel(
    info_frame,
    text='The below information displays the current "position" of the screen. This section also allows "presets" to be saved, allowing quick precise adjustments of the screen/s.',
    font=("Helvetica", 10),
    justify='left'
)
instructions.grid(row=1, column=0, columnspan=4, sticky='ew', padx=10)


# INFO FRAME
current_pos_title = WrappingLabel(
    info_frame,
    text='Current Position:',
    font=('Helvetica', 15),
    anchor='w'
)
current_pos_title.grid(row=2, column=0, columnspan=4, sticky='ew', padx=10, pady=(10, 0))

pos_label = Label(
    info_frame,
    text='Pos (steps):',
    font=("Helvetica", 10)
)
pos_value = Label(
    info_frame,
    text='0',
    width=10,
    relief='sunken'
)
pos_label.grid(row=3, column=0, sticky='w', padx=(10, 0))
pos_value.grid(row=3, column=1, sticky='w', padx=(10, 0))

def handle_position_change(new_position):
    root.after(0, lambda: pos_value.config(text=str(new_position)))

# INFO FRAME Presets 
presets = load_presets()
selected_preset = StringVar()

def save_preset(entry, presets_dic, dropdown):
    name = entry.get()
    if name:
        if name in presets_dic:
            return
        presets_dic[name] = arduino.position
        save_presets(presets_dic)
        dropdown['values'] = list(presets_dic.keys())
        entry.delete(0, END)

def delete_preset(preset_dic, dropdown, selected_var):
    name = selected_var.get()
    if name in preset_dic:
        del preset_dic[name]
        save_presets(preset_dic)
        dropdown['values'] = list(preset_dic.keys())
        selected_var.set('')

def load_preset(preset_dic, selected_var):
    name = selected_var.get()
    if name not in preset_dic:
        return
    difference = preset_dic[name] - arduino.position
    if difference > 0:
        arduino.move_up(difference)
    elif difference < 0:
        arduino.move_down(-difference)


# Heading
presets_title = WrappingLabel(
    info_frame,
    text='Presets:',
    font=('Helvetica', 15),
    anchor='w'
)
presets_title.grid(row=4, column=0, columnspan=4, sticky='ew', padx=10, pady=(10, 0))

# Save Row
save_label = Label(
    info_frame,
    text='Preset Name:',
    font=("Helvetica", 10),
    anchor='w'
)
save_entry = Entry(
    info_frame,
    width=12,
)
save_button = Button(
    info_frame,
    text='Save',
    command=lambda: save_preset(save_entry, presets, preset_dropdown)
)
save_label.grid(row=5, column=0, sticky='w', padx=(10, 0))
save_entry.grid(row=5, column=1, sticky='ew', padx=(10, 0))
save_button.grid(row=5, column=2, columnspan=2, sticky='ew', padx=(10, 0))

# Load/Delete
load_label = Label(
    info_frame,
    text='Select Preset:',
    font=("Helvetica", 10),
    anchor='w'
)
preset_dropdown = ttk.Combobox(
    info_frame,
    textvariable=selected_preset,
    values=list(presets.keys()),
    state='readonly',
    width=12
)
load_button = Button(
    info_frame,
    text='Load',
    command=lambda: load_preset(presets, selected_preset)
)
delete_button = Button(
    info_frame,
    text='Delete',
    command=lambda: delete_preset(presets, preset_dropdown, selected_preset)
)

load_label.grid(row=6, column=0, sticky='w', padx=(10, 0))
preset_dropdown.grid(row=6, column=1, sticky='ew', padx=(10, 0))
load_button.grid(row=6, column=2, sticky='ew', padx=(10, 0), )
delete_button.grid(row=6, column=3, sticky='ew')



# OP
def validate_numeric(new_value):
    #Only allow numeric input
    return new_value == '' or new_value.isdigit()

vcmd = (root.register(validate_numeric), '%P')



#Heading and Instructions
oper_heading = WrappingLabel(oper_frame, text='Screen Position Controls', font=("Helvetica", 18), anchor='w')
oper_heading.grid(row=0, column=0, columnspan=4, sticky='ew', padx=10)

oper_details = WrappingLabel(
    oper_frame,
    text='These buttons allow the screen to be controlled in steps.',
    font=("Helvetica", 10),
    justify='left',
    anchor='w'
)
oper_details.grid(row=1, column=0, columnspan=4, sticky='ew', padx=10)



# Move Up Controls
def move_up_clicked():
    value = up_entry.get()
    if value:
        arduino.move_up(int(value))

up_label = Label(
    oper_frame,
    text='Enter Step Amount:',
    font=("Helvetica", 10)
)
up_entry = Entry(
    oper_frame,
    width=10,
    validate='key',
    validatecommand=vcmd
)
up_button = Button(
    oper_frame,
    text='Move Up',
    command=move_up_clicked
)

up_label.grid(row=2, column=0, sticky='w', padx=(10, 0))
up_entry.grid(row=2, column=1, sticky='e', padx=(10, 0), pady=(0, 10))
up_button.grid(row=2, column=2, columnspan=2, sticky='ew', padx=(10), pady=(0, 10))




#Move Down Controls 
def move_down_clicked():
    value = down_entry.get()
    if value:
        arduino.move_down(int(value))

down_label = Label(
    oper_frame,
    text='Enter Step Amount:',
    font=("Helvetica", 10)
)
down_entry = Entry(
    oper_frame,
    width=10,
    validate='key',
    validatecommand=vcmd
)
down_button = Button(
    oper_frame,
    text='Move Down',
    command=move_down_clicked
)
down_label.grid(row=3, column=0, sticky='w', padx=(10, 0))
down_entry.grid(row=3, column=1, sticky='e', padx=(10, 0))
down_button.grid(row=3, column=2, columnspan=2, sticky='ew', padx=(10))


# Switch Screen Control
switch_label = Label(
    oper_frame,
    text='Switch Screen:',
    font=("Helvetica", 10)
)

switch_button = Button(
    oper_frame,
    text='Switch',
    command=lambda: arduino.switch_screen()
)
switch_label.grid(row=4, column=0, sticky='w', padx=(10, 0), pady=(30, 0))
switch_button.grid(row=4, column=2, columnspan=2, sticky='ew', padx=(10), pady=(30, 0))


# SHARED HELPERS (file / folder pickers)
def browse_file(var):
    path = filedialog.askopenfilename(
        title='Select image file',
        filetypes=[('Images', '*.tif *.tiff *.btf'), ('All files', '*.*')]
    )
    if path:
        var.set(path)

def browse_folder(var):
    path = filedialog.askdirectory(title='Select output folder')
    if path:
        var.set(path)

def add_path_row(parent, row, label_text, var, command):
    Label(parent, text=label_text, font=("Helvetica", 10)).grid(row=row, column=0, sticky='w', padx=5, pady=3)
    Entry(parent, textvariable=var, state='readonly').grid(row=row, column=1, sticky='ew', padx=5, pady=3)
    Button(parent, text='Browse...', command=command).grid(row=row, column=2, padx=5, pady=3)


# IMAGE INPUTS FRAME
input_frame.columnconfigure(1, weight=1)

reference_var = StringVar()
sample_var = StringVar()
method_var = StringVar(value='Fokker-Planck')
dark_output_var = StringVar()

add_path_row(input_frame, 0, 'Reference image:', reference_var, lambda: browse_file(reference_var))
add_path_row(input_frame, 1, 'Sample image:', sample_var, lambda: browse_file(sample_var))

Label(input_frame, text='Method:', font=("Helvetica", 10)).grid(row=2, column=0, sticky='w', padx=5, pady=3)
method_dropdown = ttk.Combobox(
    input_frame,
    textvariable=method_var,
    values=['Fokker-Planck', 'UMPA'],
    state='readonly'
)
method_dropdown.grid(row=2, column=1, sticky='ew', padx=5, pady=3)

add_path_row(input_frame, 3, 'Darkfield output:', dark_output_var, lambda: browse_folder(dark_output_var))


# ANALYSIS FRAME
analysis_frame.columnconfigure(1, weight=1)

analysis_var = StringVar()
analysis_output_var = StringVar()

Label(analysis_frame, text='Analysis:', font=("Helvetica", 10)).grid(row=0, column=0, sticky='w', padx=5, pady=3)
analysis_dropdown = ttk.Combobox(
    analysis_frame,
    textvariable=analysis_var,
    values=['SNR', 'CNR'],
    state='readonly'
)
analysis_dropdown.grid(row=0, column=1, sticky='ew', padx=5, pady=3)

add_path_row(analysis_frame, 1, 'Analysis output:', analysis_output_var, lambda: browse_folder(analysis_output_var))


arduino = ArduinoController(
    port='COM8',
    baudrate=9600,
    on_message=handle_arduino_message,
    on_position_change=handle_position_change,
    simulate=True
)
arduino.connect()
pos_value.config(text=str(arduino.position))

# disable every control except Home until the motor has homed
gated_widgets = [
    up_entry, up_button,
    down_entry, down_button,
    switch_button,
    save_entry, save_button,
    preset_dropdown, load_button, delete_button,
]

def set_controls_enabled(enabled):
    state = NORMAL if enabled else DISABLED
    for widget in gated_widgets:
        # ttk.Combobox uses 'readonly' rather than 'normal' when enabled
        if widget is preset_dropdown:
            widget.config(state='readonly' if enabled else DISABLED)
        else:
            widget.config(state=state)

set_controls_enabled(False)

root.mainloop()