#!/usr/bin/env python
# -*- coding: utf-8 -*-
import datetime
import json
import os
import numpy as np
import pandas as pd
import copy

# from plotInfo import plotEvolutionSummary
from bayes_opt import BayesianOptimization
from multiprocessing import Pool
import multiprocessing as mp


import promoterz
import evaluation

from Settings import getSettings

import evaluation

import resultInterface
from evaluation.gekko.datasetOperations import CandlestickDataset
from japonicus_options import parser
options, args = parser.parse_args()

dict_merge = lambda a, b: a.update(b) or a
gsettings = getSettings()['Global']
# Fix the shit below!
settings = getSettings()['bayesian']
bayesconf = getSettings('bayesian')
datasetconf = getSettings('dataset')
Strategy = None
percentiles = np.array([0.25, 0.5, 0.75])
all_val = []
stats = []
candleSize = 0
historySize = 0
watch = settings["watch"]
watch, DatasetRange = evaluation.gekko.dataset.selectCandlestickData(watch)


def expandGekkoStrategyParameters(IND, Strategy):
    config = {}
    IND = promoterz.parameterOperations.expandNestedParameters(IND)
    config[Strategy] = IND
    return config


def Evaluate(Strategy, parameters):
    DateRange = evaluation.gekko.dataset.getRandomDateRange(
        DatasetRange, deltaDays=settings['deltaDays']
    )
    Dataset = CandlestickDataset(watch, DateRange)
    params = expandGekkoStrategyParameters(parameters, Strategy)
    BacktestResult = evaluation.gekko.backtest.Evaluate(
        bayesconf, [Dataset], params, gsettings['GekkoURLs'][0]
    )
    BalancedProfit = BacktestResult['relativeProfit']
    return BalancedProfit


def gekko_search(**parameters):
    parallel = settings['parallel']
    num_rounds = settings['num_rounds']
    # remake CS & HS variability;
    candleSize = settings['candleSize']
    historySize = settings['historySize']
    if parallel:
        p = Pool(mp.cpu_count())
        param_list = list([(Strategy, parameters)] * num_rounds)
        scores = p.starmap(Evaluate, param_list)
        p.close()
        p.join()
    else:
        scores = [Evaluate(Strategy, parameters) for n in range(num_rounds)]
    series = pd.Series(scores)
    mean = series.mean()
    stats.append(
        [series.count(), mean, series.std(), series.min()] +
        [series.quantile(x) for x in percentiles] +
        [series.max()]
    )
    all_val.append(mean)
    return mean


def flatten_dict(d):

    def items():
        for key, value in d.items():
            if isinstance(value, dict):
                for subkey, subvalue in flatten_dict(value).items():
                    yield key + "." + subkey, subvalue

            else:
                yield key, value

    return dict(items())


def gekko_bayesian(strategy):
    print("")
    global Strategy
    Strategy = strategy
    TargetParameters = getSettings()["strategies"][Strategy]
    TargetParameters = promoterz.parameterOperations.parameterValuesToRangeOfValues(
        TargetParameters, bayesconf.parameter_spread
    )
    print("Starting search %s parameters" % Strategy)
    bo = BayesianOptimization(gekko_search, copy.deepcopy(TargetParameters))
    # 1st Evaluate
    print("")
    print("Step 1: BayesianOptimization parameter search")
    bo.maximize(init_points=settings['init_points'], n_iter=settings['num_iter'])
    max_val = bo.res['max']['max_val']
    index = all_val.index(max_val)
    s1 = stats[index]
    # 2nd Evaluate
    print("")
    print("Step 2: testing searched parameters on random date")
    max_params = bo.res['max']['max_params'].copy()
    # max_params["persistence"] = 1
    print("Starting Second Evaluation")
    gekko_search(**max_params)
    s2 = stats[-1]
    # 3rd Evaluate
    print("")
    print("Step 3: testing searched parameters on new date")
    watch = settings["watch"]
    print(max_params)
    result = Evaluate(Strategy, max_params)
    resultjson = expandGekkoStrategyParameters(max_params, Strategy)  # [Strategy]
    s3 = result
    # config.js like output
    percentiles = np.array([0.25, 0.5, 0.75])
    formatted_percentiles = [str(int(round(x * 100))) + "%" for x in percentiles]
    stats_index = (['count', 'mean', 'std', 'min'] + formatted_percentiles + ['max'])
    print("")
    print("// " + '-' * 50)
    print("// " + Strategy + ' Settings')
    print("// " + '-' * 50)
    print("// 1st Evaluate: %.3f" % s1[1])
    for i in range(len(s1)):
        print('// %s: %.3f' % (stats_index[i], s1[i]))
    print("// " + '-' * 50)
    print("// 2nd Evaluate: %.3f" % s2[1])
    for i in range(len(s2)):
        print('// %s: %.3f' % (stats_index[i], s2[i]))
    print("// " + '-' * 50)
    print("// 3rd Evaluted: %f" % s3)
    print("// " + '-' * 50)
    print("config.%s = {%s};" % (Strategy, json.dumps(resultjson, indent=2)[1:-1]))
    print('\n\n')
    print(resultInterface.parametersToTOML(resultjson))
    print("// " + '-' * 50)
    return max_params
