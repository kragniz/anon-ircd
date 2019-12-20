anon-ircd
=========

An "ircd" with very few features.


Contributing
------------

1. `git config user.name anon && git config user.email anon@localhost` (or some other name/email)

2. Make a commit

3. `git format-patch -1 --stdout | curl -F 'clbin=<-' https://clbin.com` (or run `git format-patch -1` and upload the patch somewhere else)

4. Paste the link in #dev
