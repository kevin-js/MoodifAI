import sys
sys.path.append('../../')
import httplib
import tweepy
import nltk
import re
import requests
import json
from flask import Flask, render_template, g, session, redirect, request
from project import config_data

app = Flask(__name__)
app.config.from_pyfile('config.cfg')

@app.route('/', methods=['GET', 'POST'])
def index():
	return render_template('index.html')

@app.route('/sounds', methods=['GET', 'POST'])
def sounds():
	auth = tweepy.OAuthHandler(config_data.twitter_consumer_key, config_data.twitter_consumer_secret)
	auth.set_access_token(config_data.twitter_access_key, config_data.twitter_access_secret)
	api = tweepy.API(auth)
	# get last 20 tweets from home timeline
	public_tweets = api.home_timeline()
	# TODO: generate mood scores from tweets
	sentiment_scores = sentiment_analysis(public_tweets)
	# use mood scores to get relevant artists
	track_list = get_artists_by_mood(['dark', 'energetic'])
	# create playlist of Spotify tracks
	track_spotify_id = get_spotify_track_list(track_list)
	# pass relevant data to template
	return render_template('sounds.html', tweetlist=public_tweets, spotify_id=track_spotify_id)

"""
helper functions; move to seperate file later
"""
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
	input_string = input_string.lower()
	tweet = re.sub('((www\.[^\s]+)|(https?://[^\s]+))','URL',input_string)
	input_string = re.sub('[\s]+', ' ', tweet)
	input_string = re.sub(r'#([^\s]+)', r'\1', tweet)
	input_string = input_string.strip('\'"')
	return input_string

# sentiment analysis functions
def sentiment_analysis(text_list):
	scores = {}
	wordcounts = {}
	assert isinstance(text_list, list)

	# tokenize all individual words
	for tweet in text_list:
		tweet = clean_text(tweet.text)
		tweet_tokenized = tweet.split(' ')
		for token in tweet_tokenized:
			try:
				wordcounts[token] += 1
			except:
				wordcounts[token] = 1
	return wordcounts

if __name__=="__main__":
	app.run()