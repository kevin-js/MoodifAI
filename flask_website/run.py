#!/usr/bin/python2.7

import sys
sys.path.append('../../')
sys.path.append('..')
sys.path.append('.')
import os
import tweepy
import re
import requests
import json
import urlparse
import oauth2
import pandas
#import enchant
from math import sqrt
from flask import Flask, render_template, g, session, redirect, request, url_for
import config_data

app = Flask(__name__)
app.config.from_pyfile('config.cfg')
def configure_app():
	# set up dictionary of PAD scores for emotional categories
	app.padEmotionValues = {}
	app.padEmotionValues['happy'] = (0.5900, 0.4278, 0.4607)
	app.padEmotionValues['trippy'] = (0.4350, 0.0813, -0.1046)
	app.padEmotionValues['disturbing'] = (-0.2745, 0.0860, 0.0095)
	app.padEmotionValues['angry'] = (-0.2543, 0.5081, 0.1367)
	app.padEmotionValues['eerie'] = (-0.6080, 0.3507, -0.3720)
	app.padEmotionValues['sad'] = (-0.4423, -0.2610, -0.2880)

	# set up dictionary of words mapped to normalized PAD scores; original scores on scale of 1-9
	app.padWordValues = {}
	padCSV = pandas.read_csv('valence_arousal_ratings.csv')
	for i in range(len(padCSV)):
		valence_score = (padCSV['V.Mean.Sum'][i] - 4.5)/4.5
		arousal_score = (padCSV['A.Mean.Sum'][i] - 4.5)/4.5
		dominance_score = (padCSV['D.Mean.Sum'][i] - 4.5)/4.5
		word = padCSV['Word'][i]
		app.padWordValues[word] = (valence_score, arousal_score, dominance_score)

	# set up spellchecker dictionary
	#app.spellchecker = enchant.Dict('en_US')

configure_app()

# Constants
REQUEST_TOKEN_URL = 'https://api.twitter.com/oauth/request_token'
ACCESS_TOKEN_URL = 'https://api.twitter.com/oauth/access_token'
AUTHORIZATION_BASE_URL = 'https://api.twitter.com/oauth/authorize'
TWITTER_TIMELINE_URL = 'https://api.twitter.com/1.1/statuses/home_timeline.json'

consumer = oauth2.Consumer(config_data.twitter_consumer_key, config_data.twitter_consumer_secret)
client = oauth2.Client(consumer)

@app.route('/', methods=['GET', 'POST'])
@app.route('/index', methods=['GET', 'POST'])
def index():
	return render_template('index.html')

# TODO: OAuth authentication for user login
@app.route('/login', methods=['GET', 'POST'])
def login():
	resp, content = client.request(REQUEST_TOKEN_URL, "GET")
	if resp['status'] != '200':
		return render_template('login-error.html', resp['status'])

	global request_token
	request_token = dict(urlparse.parse_qsl(content))
	return redirect('%s?oauth_token=%s' % (AUTHORIZATION_BASE_URL, request_token['oauth_token']))

@app.route('/sounds', methods=['GET', 'POST'])
def sounds():
	oauth_verifier = request.args.get('oauth_verifier')
	global request_token
	token = oauth2.Token(request_token['oauth_token'], request_token['oauth_token_secret'])
	del request_token
	token.set_verifier(oauth_verifier)
	client = oauth2.Client(consumer, token)
	resp, content = client.request(ACCESS_TOKEN_URL, "POST")
	
	access_token = dict(urlparse.parse_qsl(content))	
	auth = tweepy.OAuthHandler(config_data.twitter_consumer_key, config_data.twitter_consumer_secret)
	auth.set_access_token(access_token['oauth_token'], access_token['oauth_token_secret'])
	api = tweepy.API(auth)
	tweet_list = api.home_timeline()
	dominant_mood = sentiment_analysis(tweet_list)
	track_list = get_artists_by_mood(dominant_mood)
	track_spotify_id = get_spotify_track_list(track_list)
	return render_template('sounds.html', tweetlist=tweet_list, spotify_id=track_spotify_id, mood=dominant_mood)

# get mood categories
def get_moods():
	params = {
		'api_key' : config_data.echonest_api_key,
		'format' : 'json',
		'type' : 'mood'
	}
	response = requests.get('http://developer.echonest.com/api/v4/artist/list_terms', params=params).json()
	moods = []
	for item in response['response']['terms']:
		moods.append(item['name'])
	return moods

# get artists by mood
def get_artists_by_mood(mood_list):
	params = {
	'api_key' : config_data.echonest_api_key,
	'format' :'json',
	'bucket' : ['id:spotify-WW', 'tracks'],
	'mood' : mood_list
	}
	response = requests.get('http://developer.echonest.com/api/v4/song/search', params=params)
	return response.json()

# get artist id for spotify via echo nest
def get_spotify_track_list(track_list):
	request_string = "https://embed.spotify.com/?uri=spotify:trackset:PREFEREDTITLE:"
	for i in range(len(track_list['response']['songs']) - 1):
		track = track_list['response']['songs'][i]
		if track['tracks'] != []:
			request_string += track['tracks'][0]['foreign_id'].strip('spotify:track:')

			if i != (len(track_list['response']['songs']) -1):
				request_string += ','
			else:
				continue

	return request_string

# clean up tweets
def clean_text(input_string):
	try:
		emoji = re.compile(u'[(\U00012702-\U000127B0)(\U00010000-\U0010ffff)(\U0001F600-\U0001F64F)(\U0001F300-\U0001F5FF)(\U0001F680-\U0001F6FF)(\U0001F1E0-\U0001F1FF)+]')
	except re.error:
		emoji = re.compile(u'[\uD800-\uDBFF]+[\uDC00-\uDFFF]+')
	input_string = emoji.sub('emoji', input_string)
	input_string = input_string.lower()
	tweet = re.sub('((www\.[^\s]+)|(https?://[^\s]+))','URL',input_string)
	input_string = re.sub('[\s]+', ' ', tweet)
	input_string = re.sub(r'#([^\s]+)', r'\1', tweet)
	input_string = re.sub('@', '', tweet)
	input_string = input_string.strip('\'"')
	return input_string

# parse list of tweets into list of words
def tokenize_tweets(tweet_list):
	tweet_words = []
	for tweet in tweet_list:
		cleaned_tweet = clean_text(tweet.text)
		tokenized_tweet = cleaned_tweet.split(' ')
		for token in tokenized_tweet:
			tweet_words.append(token)
	return tweet_words

# sentiment analysis functions
def sentiment_analysis(tweet_list):
	tweet_words = tokenize_tweets(tweet_list) 
	avg_valence_score = 0
	avg_arousal_score = 0
	avg_dominance_score = 0
	n = 0
	# problem: handle emoji
	for keyword in tweet_words:
		keyword = unicode(keyword)
		try:
			scores = app.padWordValues[keyword]
			avg_valence_score += scores[0]
			avg_arousal_score += scores[1]
			avg_dominance_score += scores[2]
			n += 1
		except:
			continue
			"""
			possible_matches = app.spellchecker.suggest(keyword)
			for match in possible_matches:
				try:
					scores = app.padWordValues[match]
					avg_valence_score += scores[0]
					avg_arousal_score += scores[1]
					avg_dominance_score += scores[2]
					n += 1
					break
				except:
					pass
			"""
	if n != 0:
		avg_valence_score /= n
		avg_arousal_score /= n
		avg_dominance_score /= n

	dominant_mood = None
	# start min distance at infinity
	min_dist = float('inf')

	for emotion in app.padEmotionValues.keys():
		# using Euclidean distance of observation from cluster means
		current_emotion_score = app.padEmotionValues[emotion]
		dist = sqrt((avg_valence_score - current_emotion_score[0])**2 + (avg_arousal_score - current_emotion_score[1])**2 + (avg_dominance_score - current_emotion_score[2]) ** 2)
		if dist < min_dist:
			min_dist = dist
			dominant_mood = emotion
	return dominant_mood

def runapp():
	configure_app()
	port = int(os.environ.get('PORT', 5000))
	app.run(host='0.0.0.0', port=port)

if __name__ == "__main__":
	runapp()
