import nose
import sys
import logging
import os
import time

from shared import file_util
from shared.file_util import FileOutsideCurrentRoot
import scanner

log = logging.getLogger(__name__)
debug = log.debug
info = log.info

from shared.test_result import TestResult, TestResultSet, success, skip, error, fail
def get_paths(*items): return '\n + '.join([x.path for x in items])

global_state = None

class Watcher(nose.plugins.Plugin):
	name = 'autonose'
	score = 5000 # watcher is a mostly passive plugin so we shouldn't
	             # interfere with anyone else, however if others steal
	             # the handleError and handleFaure calls (as the
	             # xml plugin does), autonose fails to remember which
	             # tests failed - which is a Very Bad Thing (TM)
	enabled = False
	env_opt = 'AUTO_NOSE'
	
	def __init__(self, state=None):
		self.state = state
		super(self.__class__, self).__init__()
	
	def _setup(self):
		if self.state is None:
			if global_state is not None:
				self.state = global_state
			else:
				self.state = scanner.scan()
		self.start_time = time.time()
		self.files_to_run = set(self.state.affected).union(set(self.state.bad))
		if len(self.state.affected):
			info("changed files: %s" % (get_paths(*self.state.affected),))
		if len(self.state.bad):
			info("bad files: %s" % (get_paths(*self.state.bad),))

	def options(self, parser, env=os.environ):
		parser.add_option(
			"--autorun", action="store_true",
			default=env.get(self.env_opt, False), dest="autonose",
			help="enable autonose plugin")

	def configure(self, options, conf=None):
		if options.autonose:
			self.enable()
	
	def enable(self):
		self.enabled = True
		self._setup()

	def wantFile(self, filename):
		try:
			rel_file = file_util.relative(filename)
		except FileOutsideCurrentRoot:
			log.warning("ignoring file outside current root: %s" % (filename,))
			return False
		
		debug("want file %s? %s" % (filename, "NO" if (rel_file not in self.files_to_run) else "if you like..."))
		if rel_file not in self.files_to_run:
			return False
		return None # do nose's default behaviour
	
	def beforeTest(self, test):
		self._current_test = test
	
	def _test_file(self, test):
		file_path = test.address()[0]
		if not os.path.exists(file_path):
			raise RuntimeError("test.address does not contain a valid file: %s" % (test.address(),))
		return file_util.relative(file_util.source(file_path))

	def _update_test(self, test, state, err=None):
		log_lvl = debug
		if state != 'success':
			log_lvl = info
		log_lvl("test finished: %s with state: %s" % (test, state))
		debug(repr(test.address()))
		test_file = self._test_file(test)
		filestamp = None
		try:
			filestamp = self.state[self._test_file(test)]
		except FileOutsideCurrentRoot, e:
			log.warning('A test from outside the current root was run. The file is: %r' % (e.message))
		except ValueError, e:
			log.warning("test does not correspond to a known test file: %s" % (test_file,))

		if filestamp:
			result = TestResult(state, test, err, self.start_time)
			filestamp.info.add(result)
			debug(result)
		self._current_test = None
		
	def addSuccess(self, test):
		self._update_test(test, success)
	
	def handleFailure(self, test, err):
		err = test.plugins.formatFailure(test, err) or err
		self._update_test(test, fail, err)
	
	def handleError(self, test, err):
		err = test.plugins.formatError(test, err) or err
		self._update_test(test, error, err)
	
	def _addSkip(self, test):
		self._update_test(test, skip)
	
	def afterTest(self, test):
		if self._current_test is not None:
			if self._current_test is not test:
				raise RuntimeError(
					"result for %s was never recorded, but this test is %s" %
					(self._current_test, test))
			self._addSkip(self._current_test)
		debug('-'*80)
	
	def finalize(self, result=None):
		debug(self.state)
		scanner.save()
	
