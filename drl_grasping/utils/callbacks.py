import os
import tempfile
import time
from copy import deepcopy
from functools import wraps
from threading import Thread
from typing import Optional

import optuna
from sb3_contrib import TQC
from stable_baselines3 import SAC
from stable_baselines3.common.callbacks import (
    BaseCallback,
    CheckpointCallback,
    EvalCallback,
)
from stable_baselines3.common.vec_env import DummyVecEnv, VecEnv


class TrialEvalCallback(EvalCallback):
    """
    Callback used for evaluating and reporting a trial.
    """

    def __init__(
        self,
        eval_env: VecEnv,
        trial: optuna.Trial,
        n_eval_episodes: int = 5,
        eval_freq: int = 10000,
        deterministic: bool = True,
        verbose: int = 0,
        best_model_save_path: Optional[str] = None,
        log_path: Optional[str] = None,
    ):

        super(TrialEvalCallback, self).__init__(
            eval_env=eval_env,
            n_eval_episodes=n_eval_episodes,
            eval_freq=eval_freq,
            deterministic=deterministic,
            verbose=verbose,
            best_model_save_path=best_model_save_path,
            log_path=log_path,
        )
        self.trial = trial
        self.eval_idx = 0
        self.is_pruned = False

    def _on_step(self) -> bool:
        if self.eval_freq > 0 and self.n_calls % self.eval_freq == 0:
            print("Evaluating trial")
            super(TrialEvalCallback, self)._on_step()
            self.eval_idx += 1
            # report best or report current ?
            # report num_timesteps or elasped time ?
            self.trial.report(self.last_mean_reward, self.eval_idx)
            # Prune trial if need
            if self.trial.should_prune():
                self.is_pruned = True
                return False
        return True


class ParallelTrainCallback(BaseCallback):
    """
    Callback to explore (collect experience) and train (do gradient steps)
    at the same time using two separate threads.
    Normally used with off-policy algorithms and `train_freq=(1, "episode")`.

    - blocking mode: wait for the model to finish updating the policy before collecting new experience
        at the end of a rollout
    - force sync mode: stop training to update to the latest policy for collecting
        new experience

    :param gradient_steps: Number of gradient steps to do before
        sending the new policy
    :param verbose: Verbosity level
    :param sleep_time: Limit the fps in the thread collecting experience.
    """

    def __init__(
        self, gradient_steps: int = 100, verbose: int = 0, sleep_time: float = 0.0
    ):
        super(ParallelTrainCallback, self).__init__(verbose)
        self.batch_size = 0
        self._model_ready = True
        self._model = None
        self.gradient_steps = gradient_steps
        self.process = None
        self.model_class = None
        self.sleep_time = sleep_time

    def _init_callback(self) -> None:
        temp_file = tempfile.TemporaryFile()

        # Windows TemporaryFile is not a io Buffer
        # we save the model in the logs/ folder
        if os.name == "nt":
            temp_file = os.path.join("logs", "model_tmp.zip")

        self.model.save(temp_file)

        # TODO (external): add support for other algorithms
        for model_class in [SAC, TQC]:
            if isinstance(self.model, model_class):
                self.model_class = model_class
                break

        assert (
            self.model_class is not None
        ), f"{self.model} is not supported for parallel training"
        self._model = self.model_class.load(temp_file)

        self.batch_size = self._model.batch_size

        # Disable train method
        def patch_train(function):
            @wraps(function)
            def wrapper(*args, **kwargs):
                return

            return wrapper

        # Add logger for parallel training
        self._model.set_logger(self.model.logger)
        self.model.train = patch_train(self.model.train)

        # Hack: Re-add correct values at save time
        def patch_save(function):
            @wraps(function)
            def wrapper(*args, **kwargs):
                return self._model.save(*args, **kwargs)

            return wrapper

        self.model.save = patch_save(self.model.save)

    def train(self) -> None:
        self._model_ready = False

        self.process = Thread(target=self._train_thread, daemon=True)
        self.process.start()

    def _train_thread(self) -> None:
        self._model.train(
            gradient_steps=self.gradient_steps, batch_size=self.batch_size
        )
        self._model_ready = True

    def _on_step(self) -> bool:
        if self.sleep_time > 0:
            time.sleep(self.sleep_time)
        return True

    def _on_rollout_end(self) -> None:
        if self._model_ready:
            self._model.replay_buffer = deepcopy(self.model.replay_buffer)
            self.model.set_parameters(deepcopy(self._model.get_parameters()))
            self.model.actor = self.model.policy.actor
            if self.num_timesteps >= self._model.learning_starts:
                self.train()
            # Do not wait for the training loop to finish
            # self.process.join()

    def _on_training_end(self) -> None:
        # Wait for the thread to terminate
        if self.process is not None:
            if self.verbose > 0:
                print("Waiting for training thread to terminate")
            self.process.join()


class SaveVecNormalizeCallback(BaseCallback):
    """
    Callback for saving a VecNormalize wrapper every ``save_freq`` steps

    :param save_freq: (int)
    :param save_path: (str) Path to the folder where ``VecNormalize`` will be saved, as ``vecnormalize.pkl``
    :param name_prefix: (str) Common prefix to the saved ``VecNormalize``, if None (default)
        only one file will be kept.
    """

    def __init__(
        self,
        save_freq: int,
        save_path: str,
        name_prefix: Optional[str] = None,
        verbose: int = 0,
    ):
        super(SaveVecNormalizeCallback, self).__init__(verbose)
        self.save_freq = save_freq
        self.save_path = save_path
        self.name_prefix = name_prefix

    def _init_callback(self) -> None:
        # Create folder if needed
        if self.save_path is not None:
            os.makedirs(self.save_path, exist_ok=True)

    def _on_step(self) -> bool:
        if self.n_calls % self.save_freq == 0:
            if self.name_prefix is not None:
                path = os.path.join(
                    self.save_path, f"{self.name_prefix}_{self.num_timesteps}_steps.pkl"
                )
            else:
                path = os.path.join(self.save_path, "vecnormalize.pkl")
            if self.model.get_vec_normalize_env() is not None:
                self.model.get_vec_normalize_env().save(path)
                if self.verbose > 1:
                    print(f"Saving VecNormalize to {path}")
        return True


class CheckpointCallbackWithReplayBuffer(CheckpointCallback):
    """
    Callback for saving a model every ``save_freq`` steps
    :param save_freq:
    :param save_path: Path to the folder where the model will be saved.
    :param name_prefix: Common prefix to the saved models
    :param save_replay_buffer: If enabled, save replay buffer together with model (if supported by algorithm).
    :param verbose:
    """

    def __init__(
        self,
        save_freq: int,
        save_path: str,
        name_prefix: str = "rl_model",
        save_replay_buffer: bool = False,
        verbose: int = 0,
    ):
        super(CheckpointCallbackWithReplayBuffer, self).__init__(
            save_freq, save_path, name_prefix, verbose
        )
        self.save_replay_buffer = save_replay_buffer
        # self.save_replay_buffer = hasattr(self.model, "save_replay_buffer") and save_replay_buffer

    def _on_step(self) -> bool:
        if self.n_calls % self.save_freq == 0:
            path = os.path.join(
                self.save_path, f"{self.name_prefix}_{self.num_timesteps}_steps"
            )
            self.model.save(path)
            if self.verbose > 0:
                print(f"Saving model checkpoint to {path}")
            if self.save_replay_buffer:
                path_replay_buffer = os.path.join(self.save_path, "replay_buffer.pkl")
                self.model.save_replay_buffer(path_replay_buffer)
                if self.verbose > 0:
                    print(f"Saving model checkpoint to {path_replay_buffer}")
        return True


class CurriculumLoggerCallback(BaseCallback):
    """
    Custom callback for logging curriculum values.
    """

    def __init__(self, verbose=0):
        super(CurriculumLoggerCallback, self).__init__(verbose)

    def _on_step(self) -> bool:

        for infos in self.locals["infos"]:
            for info_key, info_value in infos.items():
                if not (
                    info_key.startswith("curriculum")
                    and info_key.count("__mean_step__")
                ):
                    continue

                self.logger.record_mean(
                    key=info_key.replace("__mean_step__", ""), value=info_value
                )

        return True

    def _on_rollout_end(self) -> None:

        for infos in self.locals["infos"]:
            for info_key, info_value in infos.items():
                if not info_key.startswith("curriculum"):
                    continue
                if info_key.count("__mean_step__"):
                    continue

                if info_key.count("__mean_episode__"):
                    self.logger.record_mean(
                        key=info_key.replace("__mean_episode__", ""), value=info_value
                    )
                else:
                    if isinstance(info_value, str):
                        exclude = "tensorboard"
                    else:
                        exclude = None
                    self.logger.record(key=info_key, value=info_value, exclude=exclude)
