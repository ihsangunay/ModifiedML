from scipy.sparse import csr_matrix
from sklearn.feature_extraction.text import CountVectorizer as Vectorizer
from classifiers import TransparentMultinomialNB as Classifier
from utils import ce_squared, load_imdb, ClassifierArchive
from pickle import dump
from time import time, sleep
import numpy as np
import multiprocessing as mp

# Functions

def produce_modifications(in_q, out_q):
    global experimenting
    process_name = mp.current_process().name
    while experimenting:
        if not in_q.empty():
            y_train, train_indices, target_indices, current_error = in_q.get()   
            print('Producer got an item from the queue')
            for i in target_indices:
                mod0 = np.copy(y_train)
                mod0[i] = 1 - mod0[i]
                test = mod0, train_indices, current_error
                out_q.put(test)
                
                mod1 = list(train_indices)
                mod1.remove(i)
                test = y_train, mod1, current_error
                out_q.put(test)
        else:
            sleep(0.01)

def test_modification(in_q, out_q, X_train, X_val, y_val_na):
    global experimenting
    process_name = mp.current_process().name
    while experimenting:
        if not in_q.empty():
            y_train, train_indices, current_error = in_q.get()
            print('{} got an item from the queue'.format(process_name))
            clf = Classifier()
            clf.fit(X_train[train_indices],y_train[train_indices])
            new_error = ce_squared(y_val_na, clf.predict_proba(X_val))
            if new_error < current_error:
                result = True, new_error, y_train, train_indices
            else:
                result = False, current_error, y_train, train_indices
            out_q.put(result)
        else:
            sleep(0.01)

def select_best(in_q, out_q, X_train):
    global experimenting
    global best_error
    global best_y_train
    global best_train_indices
    
    experiment_length = 2 * X_train.shape[0]
    batch_size = 1
    round_length = 2 * batch_size # One for changing, one for omitting
    start_ind = 0
    end_ind = start_ind + batch_size
    i = 0
    j = 0
    
    initial_batch = best_y_train, best_train_indices, range(start_ind, end_ind), best_error
    out_q.put(initial_batch)
    print('Experiment started')
        
    while experimenting:
        if not in_q.empty():
            improved, try_error, try_y_train, try_train_indices = in_q.get()

            if improved and try_error < best_error:
                best_error = try_error
                best_y_train = try_y_train
                best_train_indices = try_train_indices

            i += 1
            j += 1
            print(i)
            if j == experiment_length:
                experimenting = False
                print('Experiment finished.')
                break

            if i == round_length: 
                start_ind += batch_size
                end_ind += batch_size
                next_batch = best_y_train, best_train_indices, range(start_ind, end_ind), best_error
                out_q.put(next_batch)
                print('Round: {}\tCurrent Error: {}'.format(j/round_length, best_error))
                i = 0
        else:
            sleep(0.01)


# Loading

t0 = time()

vect = Vectorizer(min_df=5, max_df=1.0, binary=False, ngram_range=(1, 1))

X_train, y_train, X_test, y_test, train_corpus, test_corpus = load_imdb("./aclImdb", shuffle=True, vectorizer=vect)

y_test_na = y_test[:, np.newaxis]
y_test_na = np.append(y_test_na, 1-y_test_na, axis=1)

clf = Classifier()
clf.fit(X_train, y_train)
ctrl_clf = clf
ctrl_error = ce_squared(y_test_na, clf.predict_proba(X_test))
# Split the train dataset in 2 for validation
split = int(X_train.shape[0] / 2)

X_val = csr_matrix(X_train[split:])
y_val = np.copy(y_train[split:])

X_train = csr_matrix(X_train[:split])
y_train = np.copy(y_train[:split])

y_val_na = y_val[:, np.newaxis]
y_val_na = np.append(y_val_na, 1-y_val_na, axis=1)

train_indices = list(range(X_train.shape[0]))

best_error = ctrl_error 
best_y_train = np.copy(y_train)
best_train_indices = list(train_indices)

production_q = mp.Queue()
testing_q = mp.Queue()
selection_q = mp.Queue()

producer_task = mp.Process(target=produce_modifications, args=(production_q, testing_q))

testing_tasks = []
for _ in range(20):
    task = mp.Process(target=test_modification, args=(testing_q, selection_q, X_train, X_val, y_val_na))
    testing_tasks.append(task)
    
selection_task = mp.Process(target=select_best, args=(selection_q, production_q, X_train))

duration = time() - t0
print("Loading the experiment took {:0.2f}s.".format(duration), '\n')


# Experiment

experimenting = True

selection_task.start()
producer_task.start()
for task in testing_tasks:
    task.start()

selection_task.join()
producer_task.join()
for task in testing_tasks:
    task.join()
    
best_clf = Classifier()
best_clf.fit(X_train[best_train_indices], best_y_train[best_train_indices])

arch = ClassifierArchive(ctrl_clf, best_clf, best_train_indices, best_y_train, vect)

with open('clf6.arch','wb') as f:
    dump(arch, f)
    
print('Experiment is done, best error is {:0.4f}, ctrl error is {:0.4f}'.format() 