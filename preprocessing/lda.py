# -*- coding: utf-8 -*
"""
    This file trains an LDA model based on small word windows (e.g. 11 words per window).
    Execute via:
        python -m preprocessing/lda --dict --train
    List topics of LDA via:
        python -m preprocessing/lda --topics
    Test on a sentence via:
        python -m preprocessing/lda --test --sentence="John Doe did something."
"""
from __future__ import absolute_import, division, print_function, unicode_literals
import gensim
from gensim.models.ldamulticore import LdaMulticore
from model.datasets import load_articles, load_windows
import sys
import argparse

# All capitalized constants (except for the few below) come from this file
from config import *

LDA_CHUNK_SIZE = 10000 #2000 * 100  # docs pro batch in LDA, default ist 2000
COUNT_EXAMPLES_FOR_DICTIONARY = 100000 # 100k articles as data basis for the dictionary
COUNT_EXAMPLES_FOR_LDA = 1000 * 1000 # 1 million windows as training set
LDA_COUNT_TOPICS = 100
LDA_COUNT_WORKERS = 3
IGNORE_WORDS_BELOW_COUNT = 4 # remove very rare words from the dictionary

def main():
    """Main function, parses command line arguments and calls dict/train/topics/test."""
    
    # parse arguments
    parser = argparse.ArgumentParser()
    parser.add_argument("--dict", required=False, action="store_const", const=True,
                        help="Create the LDA's dictionary (must happen before training).")
    parser.add_argument("--train", required=False, action="store_const", const=True,
                        help="Train the LDA model.")
    parser.add_argument("--topics", required=False, action="store_const", const=True,
                        help="Show the topics of a trained LDA model.")
    parser.add_argument("--test", required=False, action="store_const", const=True,
                        help="Test the trained LDA on a sentence provided via --sentence.")
    parser.add_argument("--sentence", required=False,
                        help="An example sentence to test the LDA model on.")
    args = parser.parse_args()

    # perform requested action
    if args.dict:
        generate_dictionary()
    if args.train:
        train_lda()
    if args.topics:
        show_topics()
    if args.test:
        test_lda(args.sentence)

    if not args.dict and not args.train and not args.topics and not args.test:
        print("No option chosen, choose --dict or --train or --topics or --test.")

def generate_dictionary():
    """Generate the dictionary/vocabulary used for the LDA."""
    print("------------------")
    print("Generating LDA Dictionary")
    print("------------------")
    
    # we generate the dictionary from the same corpus that is also used to find named entities
    articles = load_articles(ARTICLES_FILEPATH)
    articles_str = []
    dictionary = gensim.corpora.Dictionary()
    update_every_n_articles = 1000

    # add words to the dictionary
    for i, article in enumerate(articles):
        articles_str.append(article.get_content_as_string().lower().split(" "))
        if len(articles_str) >= update_every_n_articles:
            print("Updating (at article %d of max %d)..." % (i, COUNT_EXAMPLES_FOR_DICTIONARY))
            dictionary.add_documents(articles_str)
            articles_str = []
        
        if i > COUNT_EXAMPLES_FOR_DICTIONARY:
            print("Reached max of %d articles." % (COUNT_EXAMPLES_FOR_DICTIONARY,))
            break

    if len(articles_str) > 0:
        print("Updating with remaining articles...")
        dictionary.add_documents(articles_str)

    print("Loaded %d unique words." % (len(dictionary.keys()),))

    # filter some rare words to save space and computation time during training
    print("Filtering rare words...")
    rare_ids = [tokenid for tokenid, docfreq in dictionary.dfs.iteritems() if docfreq < IGNORE_WORDS_BELOW_COUNT]
    dictionary.filter_tokens(rare_ids)
    dictionary.compactify()
    print("Filtered to %d unique words." % (len(dictionary.keys()),))

    # save to HDD
    print("Saving dictionary...")
    dictionary.save(LDA_DICTIONARY_FILEPATH)

def train_lda():
    """
    Train the LDA model.
    generate_dictionary() must be called before this method.
    """
    print("------------------")
    print("Training LDA model")
    print("------------------")
    
    # load dictionary, as generated by generate_dictionary()
    print("Loading dictionary...")
    dictionary = gensim.corpora.dictionary.Dictionary.load(LDA_DICTIONARY_FILEPATH)

    # generate a mapping from word id to word
    print("Generating id2word...")
    id2word = {}
    for word in dictionary.token2id:    
        id2word[dictionary.token2id[word]] = word

    # initialize LDA
    print("Initializing LDA...")
    lda_model = LdaMulticore(corpus=None, num_topics=LDA_COUNT_TOPICS, id2word=id2word, workers=LDA_COUNT_WORKERS, chunksize=LDA_CHUNK_SIZE)

    # Train the LDA model
    print("Training...")
    examples = []
    update_every_n_windows = 25000
    windows = load_windows(load_articles(ARTICLES_FILEPATH), LDA_WINDOW_SIZE, only_labeled_windows=True)
    for i, window in enumerate(windows):
        tokens_str = [token.word.lower() for token in window.tokens]
        bow = dictionary.doc2bow(tokens_str) # each window as bag of words
        examples.append(bow)
        if len(examples) >= update_every_n_windows:
            print("Updating (at window %d of max %d)..." % (i, COUNT_EXAMPLES_FOR_LDA))
            # this is where the LDA model is trained
            lda_model.update(examples)
            examples = []
        if i >= COUNT_EXAMPLES_FOR_LDA:
            print("Reached max of %d windows." % (COUNT_EXAMPLES_FOR_LDA,))
            break

    # i don't update here with the remainder of windows, because im not sure if each update step's
    # results are heavily influenced/skewed by the the number of examples
    #if len(examples) > 0:
    #    print("Updating with remaining windows...")
    #    lda_model.update(examples)

    # save trained model to HDD
    print("Saving...")
    lda_model.save(LDA_MODEL_FILEPATH)

def show_topics():
    """Shows all topics of the trained LDA model.
    May only be called after train_lda().
    """
    # load dictionary and trained model
    dictionary = gensim.corpora.dictionary.Dictionary.load(LDA_DICTIONARY_FILEPATH)
    lda_model = LdaMulticore.load(LDA_MODEL_FILEPATH)
    
    # list the topics
    topics = lda_model.show_topics(num_topics=LDA_COUNT_TOPICS, num_words=10, log=False, formatted=True)

    print("List of topics:")
    for i, topic in enumerate(topics):
        # not adding topic to the tuple here prevents unicode errors
        print("%3d:" % (i,), topic)

def test_lda(sentence):
    """Tests the trained LDA model on an example sentence, i.e. returns the topics of that
    sentence.
    May only be called after train_lda().
    
    Args:
        sentence: A sentence to test on as string.
    """
    # validate and process the sentence
    if sentence is None or len(sentence) < 1:
        raise Exception("Missing or empty 'sentence' argument.")
    
    sentence = sentence.decode("utf-8").lower().strip().split(" ")
    if len(sentence) != LDA_WINDOW_SIZE:
        print("[INFO] the token size of your sentence does not match the defined window size (%d vs %d)." % (len(sentence), LDA_WINDOW_SIZE))
    
    # load dictionary and trained model
    dictionary = gensim.corpora.dictionary.Dictionary.load(LDA_DICTIONARY_FILEPATH)
    lda_model = LdaMulticore.load(LDA_MODEL_FILEPATH)
    
    # sentence to bag of words
    bow = dictionary.doc2bow(sentence)
    
    # print topics of sentence
    print(lda_model[bow])

# --------------------

if __name__ == "__main__":
    main()
