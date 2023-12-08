# Licensed to the Software Freedom Conservancy (SFC) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The SFC licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.


# -*- coding: UTF-8 -*-


# Default Timeouts
class DefaultTimeouts:
    IMPLICIT: int = 0
    PAGE_LOAD: int = 300_000
    SCRIPT: int = 30_000


# Default Network Conditions
class DefaultNetworkConditions:
    OFFLINE: bool = False
    LATENCY: int = 0
    DOWNLOAD_THROUGHPUT: int = -1
    UPLOAD_THROUGHPUT: int = -1


# Constraint
class Constraint:
    PAGE_LOAD_STRATEGIES: set[str] = {"normal", "eager", "none"}
    UNHANDLED_PROMPT_BEHAVIORS: set[str] = {
        "dismiss",
        "dismiss and notify",
        "accept",
        "accept and notify",
        "ignore",
    }
    PAGE_SCROLL_BY_STRATEGIES: set[str] = {"steps", "pixels"}
    WINDOW_TYPES: set[str] = {"tab", "window"}
    PAGE_ORIENTATIONS: set[str] = {"portrait", "landscape"}
    PERMISSION_NAMES: set[str] = {
        "accelerometer",
        "background-sync",
        "camera",
        "geolocation",
        "gyroscope",
        "magnetometer",
        "microphone",
        "midi",
        "notifications",
        "persistent-storage",
        "push",
    }
    PERMISSION_STATES: set[str] = {"granted", "denied", "prompt"}
    POINTER_TYPES: set[str] = {"mouse", "pen", "touch"}
