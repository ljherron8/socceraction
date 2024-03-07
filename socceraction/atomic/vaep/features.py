"""Implements the feature tranformers of the VAEP framework."""
from typing import Any, Callable, Union

import numpy as np
import pandas as pd
from pandera.typing import DataFrame

import socceraction.atomic.spadl.config as atomicspadl
from socceraction.atomic.spadl import AtomicSPADLSchema
from socceraction.spadl import SPADLSchema
from socceraction.vaep.features import (
    actiontype,
    bodypart,
    bodypart_detailed,
    bodypart_detailed_onehot,
    bodypart_onehot,
    gamestates,
    simple,
    speed,
    team,
    time,
    time_delta,
)

__all__ = [
    'feature_column_names',
    'play_left_to_right',
    'gamestates',
    'actiontype',
    'actiontype_onehot',
    'bodypart',
    'bodypart_detailed',
    'bodypart_onehot',
    'bodypart_detailed_onehot',
    'team',
    'time',
    'time_delta',
    'speed',
    'location',
    'polar',
    'movement_polar',
    'direction',
    'goalscore',
]

Actions = Union[DataFrame[SPADLSchema], DataFrame[AtomicSPADLSchema]]
GameStates = list[Actions]
Features = DataFrame[Any]
FeatureTransfomer = Callable[[GameStates], Features]


def feature_column_names(fs: list[FeatureTransfomer], nb_prev_actions: int = 3) -> list[str]:
    """Return the names of the features generated by a list of transformers.

    Parameters
    ----------
    fs : list(callable)
        A list of feature transformers.
    nb_prev_actions : int, default=3  # noqa: DAR103
        The number of previous actions included in the game state.

    Returns
    -------
    list(str)
        The name of each generated feature.
    """
    spadlcolumns = [
        'game_id',
        'original_event_id',
        'action_id',
        'period_id',
        'time_seconds',
        'team_id',
        'player_id',
        'x',
        'y',
        'dx',
        'dy',
        'bodypart_id',
        'bodypart_name',
        'type_id',
        'type_name',
    ]
    dummy_actions = pd.DataFrame(np.zeros((10, len(spadlcolumns))), columns=spadlcolumns)
    for c in spadlcolumns:
        if 'name' in c:
            dummy_actions[c] = dummy_actions[c].astype(str)
    gs = gamestates(dummy_actions, nb_prev_actions)  # type: ignore
    return list(pd.concat([f(gs) for f in fs], axis=1).columns)


def play_left_to_right(gamestates: GameStates, home_team_id: int) -> GameStates:
    """Perform all action in the same playing direction.

    This changes the start and end location of each action, such that all actions
    are performed as if the team plays from left to right.

    Parameters
    ----------
    gamestates : GameStates
        The game states of a game.
    home_team_id : int
        The ID of the home team.

    Returns
    -------
    list(pd.DataFrame)
        The game states with all actions performed left to right.
    """
    a0 = gamestates[0]
    away_idx = a0.team_id != home_team_id
    for actions in gamestates:
        actions.loc[away_idx, 'x'] = atomicspadl.field_length - actions[away_idx]['x'].values
        actions.loc[away_idx, 'y'] = atomicspadl.field_width - actions[away_idx]['y'].values
        actions.loc[away_idx, 'dx'] = -actions[away_idx]['dx'].values
        actions.loc[away_idx, 'dy'] = -actions[away_idx]['dy'].values
    return gamestates


@simple
def actiontype_onehot(actions: Actions) -> Features:
    """Get the one-hot-encoded type of each action.

    Parameters
    ----------
    actions : Actions
        The actions of a game.

    Returns
    -------
    Features
        A one-hot encoding of each action's type.
    """
    X = {}
    for type_id, type_name in enumerate(atomicspadl.actiontypes):
        col = 'actiontype_' + type_name
        X[col] = actions['type_id'] == type_id
    return pd.DataFrame(X, index=actions.index)


@simple
def location(actions: Actions) -> Features:
    """Get the location where each action started.

    Parameters
    ----------
    actions : Actions
        The actions of a game.

    Returns
    -------
    Features
        The 'x' and 'y' location of each action.
    """
    return actions[['x', 'y']]


_goal_x = atomicspadl.field_length
_goal_y = atomicspadl.field_width / 2


@simple
def polar(actions: Actions) -> Features:
    """Get the polar coordinates of each action's start location.

    The center of the opponent's goal is used as the origin.

    Parameters
    ----------
    actions : Actions
        The actions of a game.

    Returns
    -------
    Features
        The 'dist_to_goal' and 'angle_to_goal' of each action.
    """
    polardf = pd.DataFrame(index=actions.index)
    dx = (_goal_x - actions['x']).abs().values
    dy = (_goal_y - actions['y']).abs().values
    polardf['dist_to_goal'] = np.sqrt(dx**2 + dy**2)
    with np.errstate(divide='ignore', invalid='ignore'):
        polardf['angle_to_goal'] = np.nan_to_num(np.arctan(dy / dx))
    return polardf


@simple
def movement_polar(actions: Actions) -> Features:
    """Get the distance covered and direction of each action.

    Parameters
    ----------
    actions : Actions
        The actions of a game.

    Returns
    -------
    Features
        The distance covered ('mov_d') and direction ('mov_angle') of each action.
    """
    mov = pd.DataFrame(index=actions.index)
    mov['mov_d'] = np.sqrt(actions.dx**2 + actions.dy**2)
    with np.errstate(divide='ignore', invalid='ignore'):
        mov['mov_angle'] = np.arctan2(actions.dy, actions.dx)
        mov.loc[actions.dy == 0, 'mov_angle'] = 0  # fix float errors
    return mov


@simple
def direction(actions: Actions) -> Features:
    """Get the direction of the action as components of the unit vector.

    Parameters
    ----------
    actions : Actions
        The actions of a game.

    Returns
    -------
    Features
        The x-component ('dx') and y-compoment ('mov_angle') of the unit
        vector of each action.
    """
    mov = pd.DataFrame(index=actions.index)
    totald = np.sqrt(actions.dx**2 + actions.dy**2)
    for d in ['dx', 'dy']:
        # we don't want to give away the end location,
        # just the direction of the ball
        # We also don't want to divide by zero
        mov[d] = actions[d].mask(totald > 0, actions[d] / totald)

    return mov


def goalscore(gamestates: GameStates) -> Features:
    """Get the number of goals scored by each team after the action.

    Parameters
    ----------
    gamestates : GameStates
        The gamestates of a game.

    Returns
    -------
    Features
        The number of goals scored by the team performing the last action of the
        game state ('goalscore_team'), by the opponent ('goalscore_opponent'),
        and the goal difference between both teams ('goalscore_diff').
    """
    actions = gamestates[0]
    teamA = actions['team_id'].values[0]
    goals = actions.type_name == 'goal'
    owngoals = actions['type_name'].str.contains('owngoal')

    teamisA = actions['team_id'] == teamA
    teamisB = ~teamisA
    goalsteamA = (goals & teamisA) | (owngoals & teamisB)
    goalsteamB = (goals & teamisB) | (owngoals & teamisA)
    goalscoreteamA = goalsteamA.cumsum() - goalsteamA
    goalscoreteamB = goalsteamB.cumsum() - goalsteamB

    scoredf = pd.DataFrame(index=actions.index)
    scoredf['goalscore_team'] = (goalscoreteamA * teamisA) + (goalscoreteamB * teamisB)
    scoredf['goalscore_opponent'] = (goalscoreteamB * teamisA) + (goalscoreteamA * teamisB)
    scoredf['goalscore_diff'] = scoredf['goalscore_team'] - scoredf['goalscore_opponent']
    return scoredf
