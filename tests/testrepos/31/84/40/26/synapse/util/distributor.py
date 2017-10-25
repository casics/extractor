# -*- coding: utf-8 -*-
# Copyright 2014, 2015 OpenMarket Ltd
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from synapse.util.logcontext import PreserveLoggingContext

from twisted.internet import defer

import logging


logger = logging.getLogger(__name__)


class Distributor(object):
    """A central dispatch point for loosely-connected pieces of code to
    register, observe, and fire signals.

    Signals are named simply by strings.

    TODO(paul): It would be nice to give signals stronger object identities,
      so we can attach metadata, docstrings, detect typoes, etc... But this
      model will do for today.
    """

    def __init__(self, suppress_failures=True):
        self.suppress_failures = suppress_failures

        self.signals = {}
        self.pre_registration = {}

    def declare(self, name):
        if name in self.signals:
            raise KeyError("%r already has a signal named %s" % (self, name))

        self.signals[name] = Signal(
            name,
            suppress_failures=self.suppress_failures,
        )

        if name in self.pre_registration:
            signal = self.signals[name]
            for observer in self.pre_registration[name]:
                signal.observe(observer)

    def observe(self, name, observer):
        if name in self.signals:
            self.signals[name].observe(observer)
        else:
            # TODO: Avoid strong ordering dependency by allowing people to
            # pre-register observations on signals that don't exist yet.
            if name not in self.pre_registration:
                self.pre_registration[name] = []
            self.pre_registration[name].append(observer)

    def fire(self, name, *args, **kwargs):
        if name not in self.signals:
            raise KeyError("%r does not have a signal named %s" % (self, name))

        return self.signals[name].fire(*args, **kwargs)


class Signal(object):
    """A Signal is a dispatch point that stores a list of callables as
    observers of it.

    Signals can be "fired", meaning that every callable observing it is
    invoked. Firing a signal does not change its state; it can be fired again
    at any later point. Firing a signal passes any arguments from the fire
    method into all of the observers.
    """

    def __init__(self, name, suppress_failures):
        self.name = name
        self.suppress_failures = suppress_failures
        self.observers = []

    def observe(self, observer):
        """Adds a new callable to the observer list which will be invoked by
        the 'fire' method.

        Each observer callable may return a Deferred."""
        self.observers.append(observer)

    @defer.inlineCallbacks
    def fire(self, *args, **kwargs):
        """Invokes every callable in the observer list, passing in the args and
        kwargs. Exceptions thrown by observers are logged but ignored. It is
        not an error to fire a signal with no observers.

        Returns a Deferred that will complete when all the observers have
        completed."""
        with PreserveLoggingContext():
            deferreds = []
            for observer in self.observers:
                d = defer.maybeDeferred(observer, *args, **kwargs)

                def eb(failure):
                    logger.warning(
                        "%s signal observer %s failed: %r",
                        self.name, observer, failure,
                        exc_info=(
                            failure.type,
                            failure.value,
                            failure.getTracebackObject()))
                    if not self.suppress_failures:
                        failure.raiseException()
                deferreds.append(d.addErrback(eb))
            results = []
            for deferred in deferreds:
                result = yield deferred
                results.append(result)
        defer.returnValue(results)
