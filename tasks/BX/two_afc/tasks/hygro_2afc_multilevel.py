import pyControl.utility as pc
from pyb import UART
from hardware_definition import right_poke, left_poke, center_poke, hygrostat, teensy_sync, reward_msPer5uL

# State machine
states = ["wait_for_center_poke", "deliver_air", "wait_for_side_poke", "left_reward", "right_reward", "inter_trial_interval", "timeout"]
events = ["center_poke", "right_poke", "left_poke", "center_poke_out", "right_poke_out", "left_poke_out", "session_timer", "finish_ITI",
        "close_final_valve", "close_final_valve_done", "center_poke_held", "set_RH_for_trial", "teensy_sync"]
initial_state = "inter_trial_interval" # starts with ITI so we have time for hygrostat to get ready

pc.v.api_class = 'online_psychometric_curve'
pc.v.subject_id = '' # place holder, will be set from setup_task()
pc.v.high_side = "left"
pc.v.low_side = "right"

# Hygrostat params
pc.v.RH_levels = [24, 30, 36, 42, 47, 53, 58, 64, 70, 76]
pc.v.RH_repetitions = [1, 2, 3, 3, 2, 2, 3, 3, 2, 1] # balance easy and near-threshold levels
# pc.v.RH_levels = [30, 40, 45, 55, 60, 70] # easy entry for new cohort
# pc.v.RH_repetitions = [4, 1, 1, 1, 1, 4]
pc.v.RH_reference = 50  # reward reference, stick to 50%

# Choosing high/low sides based on last digit of subject ID
def get_sides_from_subject_id():
    if len(pc.v.subject_id) > 0:
        idx = int(pc.v.subject_id.split("_")[0][-1]) % 2 == 1
        pc.v.high_side = "left" if idx else "right"
        pc.v.low_side = "right" if idx else "left"
    else:
        pc.v.high_side = "left"  # side associated with high RH
        pc.v.low_side = "right"  # side associated with low RH

drawer = pc.drawer(repetitions=pc.v.RH_repetitions, humidity=pc.v.RH_levels)

pc.v.flow_rate = 200 # mL/min
pc.v.current_RH = pc.choice(drawer.original)['humidity']  # start at random RH
pc.v.next_RH = pc.v.current_RH

# Timing params
pc.v.session_duration = 1.0 * pc.hour  # Session duration.
pc.v.ITI_duration = 5 * pc.second  # Inter trial interval duration. Ensure this is longer than final valve flush duration.
pc.v.timeout_duration = 4 * pc.second  # timeout for wrong trials (in addition to ITI)

pc.v.required_center_hold_duration = 300  # ms. Currently, this is ~ the absolute minimum time the current trial's odor will have to fill the tube before the final valve.
pc.v.air_delivery_duration = 1000
pc.v.final_valve_flush_duration = 0  # ensure this is shorter than the ITI

# Reward sizing
pc.v.reward_duration_multiplier = 1
pc.v.max_reward_vol = 5000 # uL
pc.v.standard_rwd_vol = 5 # uL
pc.v.standard_rwd_durations = [x / 5.0 * pc.v.standard_rwd_vol for x in reward_msPer5uL]  # Reward delivery duration (ms) [left, right].
pc.v.n_allowed_rwds = int(pc.v.max_reward_vol / (pc.v.standard_rwd_vol * pc.v.reward_duration_multiplier))  # total per session

# Implementing a big reward every n rewards 
pc.v.reward_schedule = "random" # none, every_n, random
pc.v.big_rwd_every_n = 10
pc.v.big_rwd_counter = 0
pc.v.big_rwd_multiplier = 10
pc.v.reward_durations = pc.v.standard_rwd_durations

# Variables.
pc.v.entry_time = 0
pc.v.n_total_trials = -1 # remove first "trial" b/c we start with an ITI
pc.v.n_early_errors = 0
pc.v.mov_ave_correct = 0  # moving avg of last 10 trials
pc.v.overall_ave_correct = 0  # excludes early errs
pc.v.early_err_flag = False # to avoid redrawing RH levels on next trial if early error occurs

# Reward variables (updated / used in "is_rewarded")
pc.v.choice = None
pc.v.outcome = 0
pc.v.n_correct_trials = 0
pc.v.n_rewards = 0  # total number of rewards obtained.
pc.v.ave_correct_tracker = pc.Exp_mov_ave(10)

# # Determine initial rewarded side
# if pc.v.current_RH > pc.v.RH_reference:
#     pc.v.rewarded_side = pc.v.high_side
# elif pc.v.current_RH < pc.v.RH_reference:
#     pc.v.rewarded_side = pc.v.low_side
# else:
#     pc.v.rewarded_side = pc.choice(["left", "right"])
    
# pc.v.next_rewarded_side = pc.v.rewarded_side # Next trial's rewarded side. Use this so that we can set hygrostat for the next trial before current choice is made.

### Helper functions  ###
# def set_RH():
    # hygrostat.set_humidity(pc.v.next_RH)

# # We don't need this for hygrostat stuff..
# def disable_odor_valves():
#     pass

## Moved to inter_trial_interval state logic
# def do_other_ITI_logic():
#     check_update_rewarded_side() # moving it here to update next trial after choice
#     pc.v.rewarded_side = pc.v.next_rewarded_side
#     pc.v.current_RH = pc.v.next_RH

def check_update_rewarded_side():
    pc.v.next_RH = drawer.draw()['humidity']

    if pc.v.next_RH > pc.v.RH_reference:
        pc.v.next_rewarded_side = pc.v.high_side
    elif pc.v.next_RH < pc.v.RH_reference:
        pc.v.next_rewarded_side = pc.v.low_side
    else:
        pc.v.next_rewarded_side = pc.choice(["left", "right"])    

    pc.publish_event("set_RH_for_trial")
    return

def is_rewarded(side):
    pc.v.choice = side
    if side == pc.v.rewarded_side:
        pc.v.n_correct_trials += 1
        pc.v.n_rewards += 1
        pc.v.outcome = 1

        # update reward duration for current trial
        if pc.v.reward_schedule == "every_n":
            if pc.v.n_rewards % pc.v.big_rwd_every_n == 0:
                pc.v.reward_durations = [d * pc.v.big_rwd_multiplier for d in pc.v.standard_rwd_durations]
                pc.v.big_rwd_counter += 1
            else:
                pc.v.reward_durations = pc.v.standard_rwd_durations
        elif pc.v.reward_schedule == "random":
            if pc.withprob(1.0 / pc.v.big_rwd_every_n):
                pc.v.reward_durations = [d * pc.v.big_rwd_multiplier for d in pc.v.standard_rwd_durations]
                pc.v.big_rwd_counter += 1
            else:
                pc.v.reward_durations = pc.v.standard_rwd_durations
        else:
            pc.v.reward_durations = pc.v.standard_rwd_durations
    else:
        pc.v.outcome = 0
    pc.v.ave_correct_tracker.update(pc.v.outcome)
    return pc.v.outcome

### These funcs are auto-run at beginning + end ###
def run_start():
    # Set session timer and turn on houslight.
    get_sides_from_subject_id()

    pc.set_timer("session_timer", pc.v.session_duration)
    hygrostat.begin()
    hygrostat.set_flowrate(pc.v.flow_rate)
    # set_RH() # this gets hygrostat ready for the first trial
    hygrostat.set_humidity(pc.v.next_RH)

def run_end():
    # Turn off all hardware outputs.
    right_poke.SOL.off()
    left_poke.SOL.off()
    center_poke.LED.off()
    # disable_odor_valves()
    hygrostat.off()

    # Do whatever else...save data maybe?
    pass

# State-independent behaviour.
def all_states(event):
    # When 'session_timer' event occurs stop framework to end session.
    if event == "session_timer":
        pc.stop_framework()

    # End flushing of final valve
    elif event == "close_final_valve":
        center_poke.SOL.off()

    # After new trial's odor is selected in ITI, set the odor valves
    # so there is enough time for the odor to flow thru the tubes.
    # Importantly, we make sure the final valve is closed (200 ms
    # after the "off" command [just picked this number arbitrarily, could time it])
    # so that the next trial's odor doesn't accidentally leak out.
    elif event == "set_RH_for_trial":
        if pc.timer_remaining("close_final_valve_done") == 0:
            # set_RH()
            hygrostat.set_humidity(pc.v.next_RH)
        else:
            pc.set_timer("set_RH_for_trial", 100)


### State-machine ###

def wait_for_center_poke(event):

    if event == "entry":
        center_poke.LED.on()  # cues mouse that trial is available
        pc.v.entry_time = pc.get_current_time()  # start early-error buffer
        # set_RH()  # replaced by all_states logic
    
    # If mouse pokes either side port *after* the early-error buffer
    # has elapsed, then timeout and restart the trial.
    elif (
        ((pc.get_current_time() - pc.v.entry_time) > 300)
        and (event == "left_poke" or event == "right_poke")
    ):
        center_poke.LED.off()
        # disable_odor_valves()
        pc.v.n_early_errors += 1
        pc.v.early_err_flag = True
        pc.goto_state("timeout")

    # If ms is still licking at reward port, then restart the 
    # early-error buffer when it leaves the side port.
    elif (event == "left_poke_out" or event == "right_poke_out"):
        pc.v.entry_time = pc.get_current_time()

    # Require mouse to hold nose in center port for a certain amt of time.
    # If it does not, it's not an error, just nothing happens.
    elif event == "center_poke":
        pc.set_timer("center_poke_held", pc.v.required_center_hold_duration)
    elif event == "center_poke_out":
        pc.disarm_timer("center_poke_held")
    elif event == "center_poke_held":
        pc.goto_state("deliver_air")


def deliver_air(event):
    if event == "entry":
        center_poke.LED.off()  # the light turning off will cue the mouse to the timing of odor delivery
        center_poke.SOL.on()  # delivers the odor!
        pc.timed_goto_state("wait_for_side_poke", pc.v.air_delivery_duration)
    elif event == "exit":
        # disable_odor_valves()  # close the odor valves to allow final valve to flush w clean air
        pc.set_timer("close_final_valve", (pc.v.final_valve_flush_duration))  # this will close the final valve after flush
        pc.set_timer("close_final_valve_done", (pc.v.final_valve_flush_duration + 200))  # this allows buffer time for final valve to close before switching odor valves on again


def wait_for_side_poke(event):
    if event == "entry":
        # not saving much time this way...
        # # pick the next trial's rewarded side as soon as we delivered air, so that we have enough time for hygrostat to get ready
        # # check_update_rewarded_side() 
        pass

    elif event == "right_poke":
        if is_rewarded("right"):
            pc.goto_state("right_reward")
        else:
            pc.goto_state("timeout")

    elif event == "left_poke":
        if is_rewarded("left"):
            pc.goto_state("left_reward")
        else:
            pc.goto_state("timeout")

def left_reward(event):
    # Deliver reward to left poke.
    if event == "entry":
        pc.timed_goto_state("inter_trial_interval", pc.v.reward_duration_multiplier * pc.v.reward_durations[0])
        left_poke.SOL.on()
    elif event == "exit":
        left_poke.SOL.off()


def right_reward(event):
    # Deliver reward to right poke.
    if event == "entry":
        pc.timed_goto_state("inter_trial_interval", pc.v.reward_duration_multiplier * pc.v.reward_durations[1])
        right_poke.SOL.on()
    elif event == "exit":
        right_poke.SOL.off()


def timeout(event):
    if event == "entry":
        pc.timed_goto_state("inter_trial_interval", pc.v.timeout_duration)


def inter_trial_interval(event):
    if event == "entry":
         
        # Start ITI timer. Using a timer instead of "timed_goto_state()"
        # allows us to reset the timer if mouse isn't finished licking 
        # the reward, without having to restart the entire ITI state, 
        # which would require lots of flags to only update things once, 
        # and would be generally confusing.
        pc.set_timer("finish_ITI", pc.v.ITI_duration)
        pc.v.entry_time = pc.get_current_time()

        # Update vars
        pc.v.n_total_trials += 1
        if pc.v.n_total_trials > 0: # this will skip the initial ITI at run start
            pc.v.mov_ave_correct = pc.v.ave_correct_tracker.value
            pc.v.overall_ave_correct = pc.v.n_correct_trials / max(pc.v.n_total_trials - pc.v.n_early_errors, 1)
            pc.print_variables(["n_total_trials", "n_correct_trials", "n_early_errors",
                                "mov_ave_correct", "overall_ave_correct", "rewarded_side", 
                                "choice", "outcome", "current_RH", "early_err_flag", "reward_durations", "n_rewards", "big_rwd_counter"])

        # Do any other required ITI logic in this function
        # do_other_ITI_logic()
        if not pc.v.early_err_flag: # only update if no early error on last trial
            check_update_rewarded_side() 
            pc.v.rewarded_side = pc.v.next_rewarded_side
            pc.v.current_RH = pc.v.next_RH
        
        pc.v.early_err_flag = False  # reset flag for next trial
    
    # If mouse is still licking the reward, let it keep going until it's done.
    elif (
        pc.v.outcome
        and (
                ((event == "left_poke") and pc.v.choice == "left")
                or ((event == "right_poke") and pc.v.choice == "right")
            )
        and ((pc.get_current_time() - pc.v.entry_time) < (pc.v.ITI_duration/2))
    ):
        pc.reset_timer("finish_ITI", pc.v.ITI_duration)

    # Once ITI finishes, go to first state again.
    elif event == "finish_ITI":
        pc.goto_state("wait_for_center_poke")
    
    # Check if we need to stop task for any reason.
    elif event == "exit":
        if pc.v.n_rewards >= pc.v.n_allowed_rwds:
            pc.stop_framework()