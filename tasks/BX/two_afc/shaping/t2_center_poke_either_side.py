import pyControl.utility as pc
from hardware_definition import right_port, left_port, center_port, final_valve, reward_msPer5uL

# Goal: teach mouse to poke in the center port first. Anything else while
# the light is on is bad. Then can go to either side for a reward.


# State machine
states = ["wait_for_center_poke", "deliver_air", "wait_for_side_poke", "left_reward", "right_reward", "inter_trial_interval", "timeout"]
events = ["center_poke", "right_poke", "left_poke", "center_poke_out", "right_poke_out", "left_poke_out", "session_timer", "finish_ITI", "close_final_valve", "center_poke_held"]
initial_state = "wait_for_center_poke"

# Air parameters
pc.v.required_center_hold_duration = 225  # ms
pc.v.air_delivery_duration = 1000
pc.v.final_valve_flush_duration = 500

# General Parameters.
pc.v.session_duration = 1 * pc.hour  # Session duration.
pc.v.reward_duration_multiplier = 1
pc.v.ITI_duration = 5 * pc.second  # Inter trial interval duration.
pc.v.timeout_duration = 4 * pc.second  # timeout for wrong trials (in addition to ITI)

# use volume instead of duration
# pc.v.n_allowed_rwds = 125  # total per session
pc.v.max_reward_vol = 1500 # uL
pc.v.unit_reward_vol = 10 # uL
pc.v.reward_durations = [x / 5.0 * pc.v.unit_reward_vol for x in reward_msPer5uL]  # Reward delivery duration (ms) [left, right].
pc.v.n_allowed_rwds = int(pc.v.max_reward_vol / (pc.v.unit_reward_vol * pc.v.reward_duration_multiplier))  # total per session

# Variables.
pc.v.entry_time = 0
pc.v.n_total_trials = 0
pc.v.mov_ave_correct = 0  # moving avg of last 10 trials

# Reward variables (updated / used in "is_rewarded")
pc.v.choice = "right"
pc.v.outcome = 0
pc.v.n_correct_trials = 0
pc.v.p_chose_right = 0 
pc.v.n_rewards = 0  # total number of rewards obtained.
pc.v.ave_correct_tracker = pc.Exp_mov_ave(10)
 

### These funcs are auto-run at beginning + end ###
def run_start():
    # Set session timer and turn on houslight.
    pc.set_timer("session_timer", pc.v.session_duration)

def run_end():
    # Turn off all hardware outputs.
    right_port.SOL.off()
    left_port.SOL.off()
    center_port.LED.off()
    disable_odor_valves()

    # Do whatever else...save data maybe?
    pass


### Helper funcs ###
def is_rewarded(side):
    ### Always rewarded in this task
    pc.v.choice = side
    pc.v.outcome = 1
    pc.v.n_correct_trials += 1
    pc.v.n_rewards += 1  # one reward per trial in this task
    pc.v.ave_correct_tracker.update(1)
    return pc.v.outcome


def set_odor_valves():
    pass

def disable_odor_valves():
    pass

def do_other_ITI_logic():
    pass

# State-independent behaviour.
def all_states(event):
    # When 'session_timer' event occurs stop framework to end session.
    if event == "session_timer":
        pc.stop_framework()
    elif event == "close_final_valve":
        center_port.SOL.off()


### State-machine ###

def wait_for_center_poke(event):

    # Cue mouse that trial is available
    if event == "entry":
        center_port.LED.on()
        pc.v.entry_time = pc.get_current_time()  # Start early-error buffer
        set_odor_valves()
    
    # If mouse pokes either side port *after* the early-error buffer
    # has elapsed, then timeout and restart the trial.
    elif (
        ((pc.get_current_time() - pc.v.entry_time) > 300)
        and (event == "left_poke" or event == "right_poke")
    ):
        center_port.LED.off()
        disable_odor_valves()
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


# Just air in this shaping task
def deliver_air(event):
    if event == "entry":
        center_port.LED.off()
        center_port.SOL.on()
        pc.timed_goto_state("wait_for_side_poke", pc.v.air_delivery_duration)
    elif event == "exit":
        pc.set_timer("close_final_valve", (pc.v.final_valve_flush_duration))
        disable_odor_valves()


def wait_for_side_poke(event):
    if event == "right_poke":
        if is_rewarded("right"):
            pc.v.p_chose_right = (pc.v.p_chose_right * pc.v.n_rewards + 1.0) / (pc.v.n_rewards + 1.0)
            pc.goto_state("right_reward")
        else:
            pc.goto_state("timeout")

    elif event == "left_poke":
        if is_rewarded("left"):
            pc.v.p_chose_right = (pc.v.p_chose_right * pc.v.n_rewards) / (pc.v.n_rewards + 1.0)
            pc.goto_state("left_reward")
        else:
            pc.goto_state("timeout")


def left_reward(event):
    # Deliver reward to left poke.
    if event == "entry":
        pc.timed_goto_state("inter_trial_interval", pc.v.reward_duration_multiplier * pc.v.reward_durations[0])
        left_port.SOL.on()
    elif event == "exit":
        left_port.SOL.off()


def right_reward(event):
    # Deliver reward to right poke.
    if event == "entry":
        pc.timed_goto_state("inter_trial_interval", pc.v.reward_duration_multiplier * pc.v.reward_durations[1])
        right_port.SOL.on()
    elif event == "exit":
        right_port.SOL.off()


def timeout(event):
    if event == "entry":
        pc.v.ave_correct_tracker.update(0)
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
        pc.v.mov_ave_correct = pc.v.ave_correct_tracker.value
        pc.v.n_total_trials += 1
        pc.print_variables(["n_total_trials", "n_correct_trials", "mov_ave_correct", "required_center_hold_duration"])
        
        # Auto-increase center hold duration for shaping
        if (
            ((pc.v.n_rewards == 25) or (pc.v.n_rewards == 50))
            and (pc.v.required_center_hold_duration < 300)
        ):
            pc.v.required_center_hold_duration += 75

        # Do any other required ITI logic in this function
        do_other_ITI_logic()
    
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

    elif event == "finish_ITI":
        pc.goto_state("wait_for_center_poke")
    
    elif event == "exit":
        if pc.v.n_rewards >= pc.v.n_allowed_rwds:
            pc.stop_framework()