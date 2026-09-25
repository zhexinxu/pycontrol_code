from source.gui.api import Api
import matplotlib.pyplot as plt
import numpy as np
from datetime import datetime
import psignifit as ps
import psignifit.psigniplot as psp

# online psychometric curve with nested conditions (eg flowrate)
class online_psychometric_curve_nested(Api):
    def __init__(self):
        super().__init__()

        # Names of task variables coming from the board
        self.x_var      = 'current_RH'      # stimulus value / RH
        self.choice_var = 'choice'          # "left" / "right" / None
        self.err_var    = 'early_err_flag'  # flag for early/invalid trials
        self.cond_var   = ''                # nested conditions
        self.moist_side = 'left'            # correct side for moist

        # Per-condition online psychometric data:
        # cond_value -> dict(x_vals=[...], x_cnts=[...], n_trials=[...])
        self.cond_data = {}

        self.subject_ID = None
        self.file_path = None

    # runs at the start of session
    def run_start(self):
        try: 
            plt.ion()  # interactive mode so we can update without blocking

            self.fig, self.ax = plt.subplots()

            # Black background
            self.fig.patch.set_facecolor('black')
            self.ax.set_facecolor('black')

            # White text / spines / ticks
            self.ax.tick_params(colors='white')
            for spine in self.ax.spines.values():
                spine.set_color('white')

            self.ax.xaxis.label.set_color('white')
            self.ax.yaxis.label.set_color('white')
            self.ax.title.set_color('white')

            self.fig.canvas.manager.set_window_title('Online psychometric curve')

            # Reset per-condition data and accuracy
            self.cond_data = {}
            self.acc = 0

            self.ax.set_xlabel(self.x_var)
            self.ax.set_ylabel('P(moist choice)')
            self.ax.set_ylim(-0.05, 1.05)

            self.subject_ID = self.board.data_logger.subject_ID

            # update moist side based on subject ID
            if self.subject_ID and (len(self.subject_ID) > 0):
                try:
                    self.moist_side = 'left' if int(self.subject_ID.split("_")[0][-1]) % 2 == 1 else 'right'
                except Exception:
                    pass
                print(f'moist side {self.moist_side}')
            
            if self.board.data_logger.file_path is not None:
                self.file_path = self.board.data_logger.file_path.replace('.tsv', '_psychometric.pdf')

            self.title_str = (self.subject_ID if self.subject_ID is not None else '') + \
                                datetime.now().strftime(' %Y-%m-%d')

            self.ax.set_title(self.title_str)

            self.fig.canvas.draw()
            self.fig.canvas.flush_events()
            plt.show(block=False)

        except Exception as e:
            print("Error in run_start():", repr(e))

    def _update_internal_counts(self, x_val, moist_choice, cond_val):
        """
        Update running counts for a single completed, valid trial.

        x_val        : stimulus value
        moist_choice : boolean, True if trial was a "moist" choice
        cond_val     : value of condition variable (e.g. flowrate)
        """
        try:
            # Initialize container for this condition if needed
            if cond_val not in self.cond_data:
                self.cond_data[cond_val] = {
                    'x_vals': [],
                    'x_cnts': [],
                    'n_trials': []
                }

            cd = self.cond_data[cond_val]

            if x_val in cd['x_vals']:
                idx = cd['x_vals'].index(x_val)
                cd['n_trials'][idx] += 1
                if moist_choice:
                    cd['x_cnts'][idx] += 1
            else:
                cd['x_vals'].append(x_val)
                cd['n_trials'].append(1)
                cd['x_cnts'].append(1 if moist_choice else 0)

                # keep x_vals sorted (and keep counts aligned)
                order = np.argsort(cd['x_vals'])
                cd['x_vals']   = list(np.array(cd['x_vals'])[order])
                cd['n_trials'] = list(np.array(cd['n_trials'])[order])
                cd['x_cnts']   = list(np.array(cd['x_cnts'])[order])
        except Exception as e:
            print("Error in _update_internal_counts():", repr(e))

    def plot_update(self):
        """
        Recompute proportion and error bars and update the figure.
        One curve per unique cond_var value.
        """
        if len(self.cond_data) == 0:
            return

        try:
            self.ax.clear()

            # Keep black background each redraw
            self.ax.set_facecolor('black')
            self.fig.patch.set_facecolor('black')

            # White ticks / labels / spines again (clearing resets them)
            self.ax.tick_params(colors='white')
            for spine in self.ax.spines.values():
                spine.set_color('white')

            self.ax.xaxis.label.set_color('white')
            self.ax.yaxis.label.set_color('white')
            self.ax.title.set_color('white')

            cond_values = sorted(self.cond_data.keys(), key=str)

            # choose a colormap
            cmap = plt.cm.get_cmap('tab10', max(len(cond_values), 1))

            # total trials across all conditions (for title)
            total_n = sum(sum(cd['n_trials']) for cd in self.cond_data.values())

            for i, cond_val in enumerate(cond_values):
                cd = self.cond_data[cond_val]
                if len(cd['x_vals']) == 0:
                    continue

                x = np.array(cd['x_vals'], dtype=float)
                n = np.array(cd['n_trials'], dtype=float)
                k_moist = np.array(cd['x_cnts'], dtype=float)

                p_moist = k_moist / n
                se = np.sqrt(p_moist * (1.0 - p_moist) / n)

                color = cmap(i)

                self.ax.errorbar(
                    x, p_moist, yerr=se,
                    fmt='-o',
                    color=color,
                    ecolor=color,
                    capsize=0,
                    label=f'{self.cond_var}={cond_val:g}'
                )

            self.ax.set_xlabel(self.x_var)
            self.ax.set_ylabel('P(moist choice)')
            self.ax.set_ylim(-0.05, 1.05)

            acc = self.acc if self.acc is not None else 0.0
            self.ax.set_title(
                f'{self.title_str} (N = {int(total_n)}, accuracy {acc:1.3f})'
            )

            # Legend styling for dark background
            leg = self.ax.legend()
            if leg is not None:
                for text in leg.get_texts():
                    text.set_color('white')
                leg.get_frame().set_facecolor('black')
                leg.get_frame().set_edgecolor('white')

            self.fig.canvas.draw()
            self.fig.canvas.flush_events()

        except Exception as e:
            print("Error in plot_update():", repr(e))

    # this is called repeatedly during the session
    def process_data_user(self, data):
        """
        data['vars'] is a list of named tuples with fields .name and .value.

        We wait until we see a set of variables that includes:
            - current_RH          (stimulus)
            - choice              ("left"/"right"/None)
            - early_err_flag == 0 (valid trial)
        Then we treat that as one completed trial and update the psychometric.
        """
        try:
            if len(data['vars']) == 0:
                return

            # make a simple dict: name -> value
            vars_dict = {v.name: v.value for v in data['vars']}

            # ensure we have all needed variables
            if (self.x_var not in vars_dict or
                    self.choice_var not in vars_dict or
                    self.err_var not in vars_dict):
                return

            x_val  = vars_dict[self.x_var]
            err    = vars_dict[self.err_var]
            choice = vars_dict[self.choice_var]
            self.acc = vars_dict['overall_ave_correct'] if 'overall_ave_correct' in vars_dict else None

            # get condition value (e.g. flowrate); if missing, use a default label
            if self.cond_var == '':
                self.cond_var = vars_dict["nested_var"]
                
            cond_val = vars_dict.get(self.cond_var, 'cond_default')

            # skip invalid / early-error trials
            if bool(err):
                return

            # make sure choice is defined
            if choice is None:
                return

            # Expecting string "left" or "right"
            if choice not in ("left", "right"):
                return

            moist_choice = (choice == self.moist_side)

            # Update internal counts (per condition)
            self._update_internal_counts(x_val, moist_choice, cond_val)

            # If your framework doesn't call plot_update() elsewhere,
            # you can uncomment the next line to update online:
            # self.plot_update()

        except Exception as e:
            print("Error in process_data_user():", repr(e))

    def run_stop(self):
        # Fit and save separate psychometric functions per condition
        try:
            if hasattr(self, 'fig') and self.subject_ID is not None and self.file_path is not None:
                # clear figure
                self.ax.clear()

                # Keep black background each redraw
                self.ax.set_facecolor('black')
                self.fig.patch.set_facecolor('black')

                # White ticks / labels / spines again (clearing resets them)
                self.ax.tick_params(colors='white')
                for spine in self.ax.spines.values():
                    spine.set_color('white')

                self.ax.xaxis.label.set_color('white')
                self.ax.yaxis.label.set_color('white')
                self.ax.title.set_color('white')
                
                for cond_val, cd in self.cond_data.items():
                    if sum(cd['n_trials']) <= 5:
                        continue  # not enough data to fit

                    # prepare data for psignifit: columns (x, k, n)
                    data = np.column_stack((
                        np.array(cd['x_vals'], dtype=float),
                        np.array(cd['x_cnts'], dtype=float),
                        np.array(cd['n_trials'], dtype=float)
                    ))

                    # fitting
                    res = ps.psignifit(data, experiment_type='yes/no',
                                       sigmoid='gauss', debug=True, stimulus_range=[0,100])

                    # params
                    PSE = res.threshold(0.5, unscaled=True)[0]
                    JND = (res.threshold(0.75, unscaled=True)[0]
                           - res.threshold(0.25, unscaled=True)[0]) / 2

                    print(
                        f"[{self.cond_var}={cond_val}] "
                        f"PSE: {PSE: 1.3f}, JND: {JND: 1.3f}, "
                        f"lapses: {res.parameter_estimate['gamma']:1.3f}, "
                        f"{res.parameter_estimate['lambda']:1.3f}, "
                        f"eta: {res.parameter_estimate['eta']:1.3e}"
                    )

                    # dump results in a npz file, per condition
                    base_npz_path = self.file_path.replace('.pdf', f'_{self.cond_var}-{cond_val}.npz')
                    np.savez(
                        base_npz_path,
                        data=data,
                        parameter_estimate=res.parameter_estimate,
                        parameter_confidence_intervals=res.confidence_intervals,
                        PSE=PSE,
                        JND=JND,
                        cond_var=self.cond_var,
                        cond_val=cond_val
                    )

                    # plot fitted psychometric for this condition
                    psp.plot_psychometric_function(
                        res,
                        line_color='w',
                        data_color='C0',
                        ax=self.ax,
                        estimate_type='mean'
                    )

                self.ax.set_xlabel(self.x_var)
                self.ax.set_ylabel('P(moist choice)')
                self.ax.set_ylim(-0.05, 1.05)

                self.ax.set_title(
                    f'{self.title_str} \n'
                    f'N = {sum(cd['n_trials']):g}, '
                )

                self.fig.canvas.draw()
                self.fig.canvas.flush_events()

                # save PDF
                self.fig.savefig(self.file_path)

                # Optionally close at end
                # plt.close(self.fig)

        except Exception as e:
            print("Error in online_psychometric_curve_nested.run_stop():", repr(e))