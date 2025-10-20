import csv
import threading
import random
import sys
import pathlib

import sounddevice as sd
import soundfile as sf
import numpy as np
import tkinter as tk

from collections import OrderedDict

HARMONIC_FREQUENCIES = [261.63, 293.66, 329.63, 392.00, 440.00, 523.25, 587.33, 659.25, 783.99]
UNRELATED_FREQUENCIES = [227, 317, 354, 407, 463, 539, 569, 747, 823] # EXPLANATION REQUIRED
AUDIO_SAMPLE_RATE = 48000 
# The below line should automatically pick the natural sample rate of the device
# AUDIO_SAMPLE_RATE = sd.query_devices(args.device, 'output')['default_samplerate']


# Sound effect configuration
HARMONICS_N = 10
ATTACK_LENGTH_MS = 50
HOLD_LENGTH_MS = 200
RELEASE_LENGTH_MS = 250


class App():

    # ----- INITIALIZATION LOGIC -----

    def __init__(self, root, *args, **kwargs):
        self.root = root
        #self.style = ttk.Style()

        self.event_queue = []
        self.scenario_frames = {}
        self.special_widgets = {}
        self.per_scenario_data = OrderedDict()
        self.effect_callback = {}
        self.randomized_scenario_order = []
        self.font_size = 12
        self.disable_trial_buttons = True
        self.playback_is_active = True
        self.is_last_trial_of_scenario = False
        self.scenario_number = 0
        self.results_file = None

        self.root.title("Study Testing Application")
        self.root.geometry('500x300')
        #self.style.configure('.', font=('Helvetica', self.font_size), bg='black')

        # The swappable_frame_base is always scaled to be a max size 1:1 square
        # Used as the parent for all "pages" of the application
        self.swappable_frame_base = tk.Frame(root)
        self.swappable_frame_base.columnconfigure(0, weight=1)
        self.swappable_frame_base.rowconfigure(0, weight=1)

        # --- LANDING PAGE INITIALIZATION ---
        entry_screen_frame = self.create_swappable_frame()
        self.volume_slider = tk.Scale(entry_screen_frame, from_=0, to=100,
                                      orient=tk.HORIZONTAL, tickinterval=0, showvalue=0)

        self.participant_id = None
        self.participant_id_entry = tk.Entry(entry_screen_frame)
        participant_id_label = tk.Label(entry_screen_frame, 
                                         text="Participant ID:")

        test_audio = self.create_beep_audio(HARMONIC_FREQUENCIES[4], AUDIO_SAMPLE_RATE)
        callback = lambda _: self.play_audio(test_audio) 
        test_audio_button = tk.Button(entry_screen_frame, text="Test Sound")
        test_audio_button.bind('<Button-1>', callback)

        entry_next_button = tk.Button(entry_screen_frame, text="Start Test")
        def start_if_viable(_):
            if self.participant_id_entry.get() and self.volume_slider.get():
                self.participant_id = self.participant_id_entry.get()
                self.results_file = self.get_results_file(f'{self.participant_id}.csv')
                self.start_next_scenario()

        entry_next_button.bind('<Button-1>', start_if_viable)

        entry_screen_frame.columnconfigure(0, weight=1)
        entry_screen_frame.rowconfigure(list(range(5)), weight=1)
        participant_id_label.grid(row=0)
        self.participant_id_entry.grid(row=1, sticky='nwse', pady=(5, 20))
        self.volume_slider.grid(row=2, sticky='nwse', pady=5)
        test_audio_button.grid(row=3, sticky='nwse')
        entry_next_button.grid(row=4, sticky='nwse', pady=(20,5))
        self.scenario_frames['entry'] = entry_screen_frame
        # --- LANDING PAGE INITIALIZATION ---

        # --- END PAGE INITIALIZATION ---
        thank_you_screen_frame = self.create_swappable_frame()
        text = tk.Label(thank_you_screen_frame, text="Thank you\nfor participating")
        text.pack()
        self.scenario_frames['last'] = thank_you_screen_frame
        # --- END PAGE INITIALIZATION ---

        # call sd.play early to prevent an issue with first playback
        sd.play([0.], AUDIO_SAMPLE_RATE)

        # Initialize essential continuously ran functions
        self.root.bind('<Configure>', self.__init_dynamic_resize_everything)
        self.handle_event_queue()


    def __init_dynamic_resize_everything(self, event):
        if (event.widget != self.root): return

        # Below value is somewhat hard-coded
        FONT_SCALING = 14

        width = event.width
        height = event.height

        new_font_size = int(height / FONT_SCALING)
        if new_font_size != self.font_size:
            self.font_size = new_font_size
            new_font = ("Helvetica", self.font_size)
            #self.style.configure('.', font=("Helvetica", self.font_size))
            self.participant_id_entry.config(font=new_font)

        square_sidelength = min(width, height)
        self.swappable_frame_base.place(anchor='center', relx=.5, rely=.5, width=square_sidelength, height=square_sidelength)

        self.volume_slider.config(width=height//5, sliderlength=height//5)


    def create_swappable_frame(self):
        frame = tk.Frame(self.swappable_frame_base)
        frame.grid(row=0, column=0, sticky='nwse')
        frame.grid_remove()
        return frame


    def add_scenario(self, scenario_name, frequencies=None):
        self.scenario_number += 1
        sounds = []
        if frequencies is None:
            # Silence = one 0.0 sample audio clip
            sounds = [np.zeros(1) for x in range(3*3)]

        for freq in frequencies if frequencies else ():
            sounds.append(self.create_beep_audio(freq, AUDIO_SAMPLE_RATE))

        scenario_frame = self.create_swappable_frame()
        self.scenario_frames[scenario_name] = scenario_frame
        self.randomized_scenario_order.append(scenario_name)
        random.shuffle(self.randomized_scenario_order)

        self.special_widgets.setdefault(scenario_name, {})
        self.effect_callback.setdefault(scenario_name, {})

        for i in range(3*3):
            effect_callback = self.trial_button_press_effect(i, sounds[i], scenario_name)
            self.effect_callback[scenario_name][i] = effect_callback
            callback = self.on_trial_button_press(i, sounds[i], scenario_name)

            button = tk.Frame(scenario_frame, bg='blue')#style=f'{scenario_name}{i}.TFrame')
            button.bind('<Button-1>', callback)
            button.grid(row = i//3, column = i%3, sticky='nwse', padx=2, pady=2)

            #self.style.configure(f'{scenario_name}{i}.TFrame', background='blue')
            button.grid_remove()

            scenario_frame.columnconfigure(i%3, weight=1)
            scenario_frame.rowconfigure(i//3, weight=1)

            self.special_widgets[scenario_name][i] = button


        scenario_label = tk.Label(scenario_frame)
        scenario_label.grid(row=0, column=1)
        self.special_widgets[scenario_name]['scenario-label'] = scenario_label
        next_button = tk.Button(scenario_frame, text="Ready?")
        next_button.grid(row=1, column=1, sticky='nwse')
        next_button.bind('<Button-1>', self.on_next_button_press(scenario_name))
        self.special_widgets[scenario_name]['next'] = next_button



    # ----- APPLICATION FLOW CONTROL -----

    def on_next_button_press(self, scenario_name):
        def callback(*_):
            for i in range(3*3):
                self.special_widgets[scenario_name][i].grid()
            self.special_widgets[scenario_name]['next'].grid_remove()
            self.special_widgets[scenario_name]['scenario-label'].grid_remove()

            self.get_next_trial(scenario_name)

            self.playback_right_moves(scenario_name)
        return callback


    def on_trial_end(self, scenario_name):
        self.save_data(scenario_name)

        if self.is_last_trial_of_scenario:
            self.is_last_trial_of_scenario = False
            self.start_next_scenario()

        for i in range(3*3):
            self.special_widgets[scenario_name][i].grid_remove()
        self.special_widgets[scenario_name]['next'].grid()


    def start_next_scenario(self, specific_scenario=None):
        if specific_scenario is None:
            if self.randomized_scenario_order:
                specific_scenario = self.randomized_scenario_order.pop(0)
                scenario_n = self.scenario_number - len(self.randomized_scenario_order)
                label_text = f"{specific_scenario.capitalize()} ({scenario_n} / {self.scenario_number})"
                self.special_widgets[specific_scenario]['scenario-label'].config(text=label_text)
            else:
                self.save_data()
                specific_scenario = 'last'

        for scenario_frame in self.scenario_frames.values():
            scenario_frame.grid_remove()

        scenario_to_activate = self.scenario_frames[specific_scenario]
        scenario_to_activate.grid()


    def get_next_trial(self, scenario_name):
        """
        Determines both the length of the next trial and the right answer
        And whether or not to continue

        Currently: 
        Got last one right: +1 length
        Got one wrong: -1 length

        Stop whenever the user has failed 3 trials of the same length
        Still runs one more scenario after that (should maybe be fixed)
        """

        self.per_scenario_data.setdefault(scenario_name, [])
        if not self.per_scenario_data[scenario_name]:
            self.per_scenario_data[scenario_name].append(([random.randint(0,8)], []))
            return

        failures_per_length = [0]

        for right_moves, inputs in self.per_scenario_data[scenario_name]:
            failures_per_length.append(0)
            if right_moves != inputs:
                failures_per_length[len(right_moves)] += 1
            if failures_per_length[len(right_moves)] >= 3:
                self.is_last_trial_of_scenario = True
                break

        prev_right, prev_inputs = self.per_scenario_data[scenario_name][-1]
        prev_length = len(prev_right)
        if prev_right == prev_inputs:
            prev_length += 1
        else:
            prev_length = max(prev_length-1, 1)

        right_moves = [random.randint(0,8) for _ in range(prev_length)]
        self.per_scenario_data[scenario_name].append((right_moves, []))



    # ----- TRIAL BUTTON LOGIC -----

    def trial_button_press_effect(self, button_index, data, scenario_name):
        """
        Audio playback and visual effect handling for a trial button press.
        Has no side effect causing logic beyond the visual.
        """
        def callback(*_):
            self.play_audio(data)
            #self.style.configure(f'{scenario_name}{button_index}.TFrame', background='orange')

            self.special_widgets[scenario_name][button_index].config(bg='orange')
            def turn_to_blue(*_):
                pass
                self.special_widgets[scenario_name][button_index].config(bg='blue')
                #self.style.configure(f'{scenario_name}{button_index}.TFrame', background='blue')
            self.run_after(ATTACK_LENGTH_MS+HOLD_LENGTH_MS, turn_to_blue)
        return callback


    def on_trial_button_press(self, button_index, data, scenario_name):
        def reactivate_buttons():
            if not self.playback_is_active:
                self.disable_trial_buttons = False

        BUTTON_PRESS_DELAY_MS = 100
        def callback(*_):
            if self.disable_trial_buttons or self.playback_is_active: return
            self.disable_trial_buttons = True
            self.effect_callback[scenario_name][button_index]()
            self.per_scenario_data[scenario_name][-1][1].append(button_index)
            right_inputs, trial_inputs_so_far = self.per_scenario_data[scenario_name][-1]
            if len(trial_inputs_so_far) >= len(right_inputs):
                after_last_delay = ATTACK_LENGTH_MS+HOLD_LENGTH_MS+RELEASE_LENGTH_MS
                self.run_after(after_last_delay, lambda: self.on_trial_end(scenario_name))
            else:
                self.run_after(BUTTON_PRESS_DELAY_MS, reactivate_buttons)

        return callback

    def playback_right_moves(self, scenario_name):
        BETWEEN_PRESS_DELAY = 500
        self.playback_is_active = True
        self.disable_trial_buttons = True

        right_moves, _ = self.per_scenario_data[scenario_name][-1]

        def press_one(moves_n):
            if moves_n >= len(right_moves):
                self.playback_is_active = False
                self.disable_trial_buttons = False
                return
            move = right_moves[moves_n]
            self.effect_callback[scenario_name][move]()
            moves_n += 1
            self.run_after(BETWEEN_PRESS_DELAY, lambda: press_one(moves_n))

        self.run_after(BETWEEN_PRESS_DELAY, lambda: press_one(0))



    # ----- DATA SAVING TO FILE -----

    @staticmethod
    def get_results_file(filename):
        results_dir = App.get_results_folder()
        result_filename = results_dir / filename
        if result_filename.exists():
            print(f"Error: file {result_filename.absolute()} already exists.", file=sys.stderr)
            quit()
        return result_filename

    @staticmethod
    def get_results_folder():
        current_dir = pathlib.Path('.')
        result_dir_name = 'results'
        result_dir = current_dir / result_dir_name
        if not (result_dir.exists() and result_dir.is_dir()):
            try:
                result_dir.mkdir(exist_ok=True)
            except FileExistsError:
                print(f"Error: file 'results' already exists but is not a directory" \
                    f"\nAt location {result_dir.absolute()}", file=sys.stderr)
                quit()
        return result_dir

    def save_data(self, write_scenario_name=None):
        """
        Output format:
        ID, SCENARIO_NAME, TRIAL_N, TRIAL_LENGTH, USER_ANSWERED_CORRECTLY
        Scenarios will be in order of activation (App.per_scenario_data is OrderedDict)

        If scenario_name is provided, append one line (last trial in that scenario)
        Otherwise rewrite file based on all data in self.per_scenario_data
        """

        participant_id = self.participant_id
        data_to_write = []
        file_mode = None

        if write_scenario_name:
            file_mode = 'a'
            last_trial = self.per_scenario_data[write_scenario_name][-1]
            trial_n = len(self.per_scenario_data[write_scenario_name])
            trial_length = len(last_trial[0])
            user_answered_correctly = (last_trial[0] == last_trial[1])
            data_to_write.append((participant_id, write_scenario_name, 
                                  trial_n, trial_length, user_answered_correctly))
        else:
            file_mode = 'w'
            for scenario_name, scenario_data in self.per_scenario_data.items():
                for i, trial in enumerate(scenario_data):
                    trial_n = i + 1
                    trial_length = len(trial[0])
                    user_answered_correctly = (trial[0] == trial[1])
                    data_to_write.append((participant_id, scenario_name, 
                                          trial_n, trial_length, user_answered_correctly))

        with open(self.results_file, file_mode, newline='') as csvfile:
            results = csv.writer(csvfile)
            for row in data_to_write:
                results.writerow(row)



    # ----- CUSTOM EVENT QUEUE IMPLEMENTATION -----

    def run_after(self, time_ms, function):
        """
        Replacement for Tkinter's .after().
        Requires one call to App.handle_event_queue() during initialization to work
        """
        self.event_queue.append([time_ms, function])


    def handle_event_queue(self):
        """
        Tkinter's .after() seems to have issue dealing with multiple 'waits' going on at once.
        Should be the only thing calling tk.Tk().after().
        Queued functions (App.run_after()) will run (about) within a window of RUN_AGAIN_AFTER_MS ms.
        """
        RUN_AGAIN_AFTER_MS = 20
        for i, (time, function) in enumerate(self.event_queue):
            time -= RUN_AGAIN_AFTER_MS
            if time <= 0:
                function()
                self.event_queue.pop(i)
                continue
            self.event_queue[i][0] = time
        self.root.after(RUN_AGAIN_AFTER_MS, self.handle_event_queue)



    # ----- AUDIO HELPER METHODS -----

    def play_audio(self, data):
        # maps volume [0,100] to [0, 0.99] in an exponential curve
        vol = (100**(self.volume_slider.get()/100-1)-0.01)
        # volume is only determined at the start of playback for the entire file
        sd.play(data*vol, AUDIO_SAMPLE_RATE)


    @staticmethod
    def create_beep_audio(frequency_hz, sample_rate):
        sample_count = lambda length_ms : int(length_ms / 1000 * sample_rate)

        audio_sample_count = sample_count(ATTACK_LENGTH_MS + HOLD_LENGTH_MS + RELEASE_LENGTH_MS)
        time_samples = np.arange(audio_sample_count) / sample_rate

        sum_formula = lambda k: np.sin(time_samples*(2*np.pi)*frequency_hz*k) / k
        sum_components = list(map(sum_formula, range(1, HARMONICS_N+1)))
        sawtooth_wave = 2/np.pi*np.sum(sum_components, axis=0)

        attack_sample_count = sample_count(ATTACK_LENGTH_MS)
        attack_x_samples = np.arange(attack_sample_count) / attack_sample_count # [0, 1]
        attack_samples = 1 - np.power(1 - attack_x_samples, 3)

        hold_sample_count = sample_count(HOLD_LENGTH_MS)
        hold_samples = np.full(hold_sample_count, 1)

        release_sample_count = audio_sample_count - attack_sample_count - hold_sample_count
        release_x_samples = 1 - (np.arange(release_sample_count) / release_sample_count) # [1, 0]
        release_samples = 1 - np.cos((release_x_samples * np.pi) / 2)

        envelope = np.concatenate((attack_samples, hold_samples, release_samples))
        beep = sawtooth_wave * envelope

        return beep



def main():
    # Make sure we can save the data
    App.get_results_folder()

    root = tk.Tk()
    gui = App(root)

    gui.add_scenario('harmonic', HARMONIC_FREQUENCIES)
    gui.add_scenario('unrelated', UNRELATED_FREQUENCIES)
    gui.add_scenario('silent')

    gui.start_next_scenario('entry')

    root.mainloop()

if __name__ == '__main__':
    main()
