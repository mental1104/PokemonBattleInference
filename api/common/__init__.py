import os
import csv

DATA_PATH = os.path.dirname(__file__) + '/data'

TYPE_EFFICACY = []
with open(DATA_PATH + '/type_efficacy.csv') as f:
    reader = csv.reader(f)
    next(reader)
    
    rows = []
    while True:
        try:
            row = next(reader)
        except StopIteration:
            break
        rows.append(row)
    
    type_list = list(set([row[0] for row in rows]))
    TYPE_EFFICACY = [[0 for _ in range(len(type_list) + 1)] for _ in range(len(type_list) + 1)]
    # 初始化一个邻接矩阵
    for row in rows:
        TYPE_EFFICACY[int(row[0])][int(row[1])] = int(row[2])
