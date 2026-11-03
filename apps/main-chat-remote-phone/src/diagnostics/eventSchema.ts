// Generated mirror of diagnostics/contracts/event-v1.schema.json; parity-tested.
export default {
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:nc:diagnostics:event:1",
  "type": "object",
  "properties": {
    "schema_version": {
      "const": 1,
      "type": "integer"
    },
    "event_id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 128,
      "pattern": "^[A-Za-z0-9_.:/-]+$"
    },
    "producer_id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 128,
      "pattern": "^[A-Za-z0-9_.:/-]+$"
    },
    "sequence": {
      "type": "integer",
      "minimum": 1,
      "maximum": 9007199254740991
    },
    "component": {
      "enum": [
        "desktop",
        "backend",
        "phone.js",
        "phone.native",
        "diagnostics"
      ]
    },
    "build_id": {
      "anyOf": [
        {
          "type": "string",
          "minLength": 1,
          "maxLength": 128,
          "pattern": "^[A-Za-z0-9_.:/-]+$"
        },
        {
          "type": "null"
        }
      ]
    },
    "build_unavailable_reason": {
      "anyOf": [
        {
          "type": "string",
          "minLength": 1,
          "maxLength": 128,
          "pattern": "^[A-Za-z0-9_.:/-]+$"
        },
        {
          "type": "null"
        }
      ]
    },
    "wall_time_utc": {
      "type": "string",
      "format": "date-time",
      "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{3}Z$"
    },
    "monotonic_ms": {
      "type": "number",
      "minimum": 0,
      "maximum": 9007199254740991
    },
    "clock_id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 128,
      "pattern": "^[A-Za-z0-9_.:/-]+$"
    },
    "level": {
      "enum": [
        "debug",
        "info",
        "warning",
        "error"
      ]
    },
    "event_name": {
      "enum": [
        "transaction.operation",
        "presentation.position",
        "transport.exchange",
        "diagnostics.validation_failed",
        "diagnostics.sink_failed",
        "diagnostics.capture_state",
        "diagnostics.policy",
        "relay.transition"
      ]
    },
    "trace_id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 128,
      "pattern": "^[A-Za-z0-9_.:/-]+$"
    },
    "operation_id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 128,
      "pattern": "^[A-Za-z0-9_.:/-]+$"
    },
    "parent_operation_id": {
      "anyOf": [
        {
          "type": "string",
          "minLength": 1,
          "maxLength": 128,
          "pattern": "^[A-Za-z0-9_.:/-]+$"
        },
        {
          "type": "null"
        }
      ]
    },
    "phase": {
      "enum": [
        "begin",
        "decision",
        "wait",
        "progress",
        "end",
        "snapshot"
      ]
    },
    "outcome": {
      "enum": [
        "pending",
        "success",
        "rejected",
        "cancelled",
        "failed",
        "observed"
      ]
    },
    "basis": {
      "enum": [
        "observed",
        "derived",
        "hypothesis"
      ]
    },
    "links": {
      "type": "array",
      "maxItems": 64,
      "items": {
        "type": "object",
        "properties": {
          "relation": {
            "enum": [
              "caused_by",
              "retry_of",
              "acknowledges",
              "cleanup_of",
              "part_of"
            ]
          },
          "event_id": {
            "anyOf": [
              {
                "type": "string",
                "minLength": 1,
                "maxLength": 128,
                "pattern": "^[A-Za-z0-9_.:/-]+$"
              },
              {
                "type": "null"
              }
            ]
          },
          "operation_id": {
            "anyOf": [
              {
                "type": "string",
                "minLength": 1,
                "maxLength": 128,
                "pattern": "^[A-Za-z0-9_.:/-]+$"
              },
              {
                "type": "null"
              }
            ]
          }
        },
        "required": [
          "relation",
          "event_id",
          "operation_id"
        ],
        "additionalProperties": false
      }
    },
    "context": {
      "type": "object",
      "properties": {
        "connection_id": {
          "type": "string",
          "minLength": 1,
          "maxLength": 128,
          "pattern": "^[A-Za-z0-9_.:/-]+$"
        },
        "session_id": {
          "type": "string",
          "minLength": 1,
          "maxLength": 128,
          "pattern": "^[A-Za-z0-9_.:/-]+$"
        },
        "reply_id": {
          "type": "string",
          "minLength": 1,
          "maxLength": 128,
          "pattern": "^[A-Za-z0-9_.:/-]+$"
        },
        "segment_id": {
          "type": "string",
          "minLength": 1,
          "maxLength": 128,
          "pattern": "^[A-Za-z0-9_.:/-]+$"
        },
        "chunk_id": {
          "type": "string",
          "minLength": 1,
          "maxLength": 128,
          "pattern": "^[A-Za-z0-9_.:/-]+$"
        },
        "frame_id": {
          "type": "string",
          "minLength": 1,
          "maxLength": 128,
          "pattern": "^[A-Za-z0-9_.:/-]+$"
        },
        "generation": {
          "type": "integer",
          "minimum": 0,
          "maximum": 9007199254740991
        },
        "attempt": {
          "type": "integer",
          "minimum": 0,
          "maximum": 9007199254740991
        },
        "thread_id": {
          "type": "string",
          "minLength": 1,
          "maxLength": 128,
          "pattern": "^[A-Za-z0-9_.:/-]+$"
        },
        "task_id": {
          "type": "string",
          "minLength": 1,
          "maxLength": 128,
          "pattern": "^[A-Za-z0-9_.:/-]+$"
        }
      },
      "required": [],
      "additionalProperties": false
    },
    "data": {
      "type": "object"
    }
  },
  "required": [
    "schema_version",
    "event_id",
    "producer_id",
    "sequence",
    "component",
    "build_id",
    "build_unavailable_reason",
    "wall_time_utc",
    "monotonic_ms",
    "clock_id",
    "level",
    "event_name",
    "trace_id",
    "operation_id",
    "parent_operation_id",
    "phase",
    "outcome",
    "basis",
    "links",
    "context",
    "data"
  ],
  "additionalProperties": false,
  "allOf": [
    {
      "if": {
        "properties": {
          "event_name": {
            "const": "diagnostics.policy"
          }
        },
        "required": [
          "event_name"
        ]
      },
      "then": {
        "properties": {
          "data": {
            "type": "object",
            "additionalProperties": false,
            "required": [
              "site",
              "status",
              "revision",
              "effective"
            ],
            "properties": {
              "site": {
                "const": "diagnostics.policy"
              },
              "status": {
                "enum": [
                  "applied",
                  "rejected",
                  "unavailable",
                  "mismatch"
                ]
              },
              "revision": {
                "type": "string",
                "pattern": "^[A-Za-z0-9_-]{1,64}$"
              },
              "reason": {
                "enum": [
                  "invalid_policy",
                  "missing_file",
                  "oversized_file",
                  "read_failed",
                  "native_unavailable",
                  "native_rejected",
                  "revision_mismatch",
                  "transport_failed"
                ]
              },
              "effective": {
                "type": "object",
                "additionalProperties": false,
                "required": [
                  "acquisition",
                  "encoding",
                  "transfer",
                  "buffering",
                  "native_playback",
                  "handoff",
                  "ownership",
                  "microphone",
                  "lifecycle",
                  "uncategorized"
                ],
                "properties": {
                  "acquisition": {
                    "enum": [
                      "off",
                      "errors",
                      "state",
                      "trace"
                    ]
                  },
                  "encoding": {
                    "enum": [
                      "off",
                      "errors",
                      "state",
                      "trace"
                    ]
                  },
                  "transfer": {
                    "enum": [
                      "off",
                      "errors",
                      "state",
                      "trace"
                    ]
                  },
                  "buffering": {
                    "enum": [
                      "off",
                      "errors",
                      "state",
                      "trace"
                    ]
                  },
                  "native_playback": {
                    "enum": [
                      "off",
                      "errors",
                      "state",
                      "trace"
                    ]
                  },
                  "handoff": {
                    "enum": [
                      "off",
                      "errors",
                      "state",
                      "trace"
                    ]
                  },
                  "ownership": {
                    "enum": [
                      "off",
                      "errors",
                      "state",
                      "trace"
                    ]
                  },
                  "microphone": {
                    "enum": [
                      "off",
                      "errors",
                      "state",
                      "trace"
                    ]
                  },
                  "lifecycle": {
                    "enum": [
                      "off",
                      "errors",
                      "state",
                      "trace"
                    ]
                  },
                  "uncategorized": {
                    "enum": [
                      "off",
                      "errors",
                      "state",
                      "trace"
                    ]
                  }
                }
              }
            }
          }
        }
      }
    },
    {
      "if": {
        "properties": {
          "event_name": {
            "const": "transaction.operation"
          }
        },
        "required": [
          "event_name"
        ]
      },
      "then": {
        "properties": {
          "data": {
            "type": "object",
            "properties": {
              "begin_suppressed": {
                "type": "boolean"
              },
              "begin_recorded": {
                "type": "boolean"
              },
              "site": {
                "type": "string",
                "minLength": 1,
                "maxLength": 128,
                "pattern": "^[A-Za-z0-9_.:/-]+$"
              },
              "failure_kind": {
                "type": "string",
                "minLength": 1,
                "maxLength": 128,
                "pattern": "^[A-Za-z0-9_.:/-]+$"
              },
              "condition": {
                "type": "string",
                "minLength": 1,
                "maxLength": 128,
                "pattern": "^[A-Za-z0-9_.:/-]+$"
              },
              "expected": {
                "anyOf": [
                  {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 128,
                    "pattern": "^[A-Za-z0-9_.:/-]+$"
                  },
                  {
                    "type": "boolean"
                  },
                  {
                    "type": "number",
                    "minimum": -9007199254740991,
                    "maximum": 9007199254740991
                  },
                  {
                    "type": "null"
                  }
                ]
              },
              "actual": {
                "anyOf": [
                  {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 128,
                    "pattern": "^[A-Za-z0-9_.:/-]+$"
                  },
                  {
                    "type": "boolean"
                  },
                  {
                    "type": "number",
                    "minimum": -9007199254740991,
                    "maximum": 9007199254740991
                  },
                  {
                    "type": "null"
                  }
                ]
              },
              "origin_event_id": {
                "type": "string",
                "minLength": 1,
                "maxLength": 128,
                "pattern": "^[A-Za-z0-9_.:/-]+$"
              },
              "exception_type": {
                "type": "string",
                "minLength": 1,
                "maxLength": 128,
                "pattern": "^[A-Za-z0-9_.:/-]+$"
              },
              "frames": {
                "type": "array",
                "items": {
                  "type": "object",
                  "properties": {
                    "module": {
                      "type": "string",
                      "minLength": 1,
                      "maxLength": 128,
                      "pattern": "^[A-Za-z0-9_.:/-]+$"
                    },
                    "function": {
                      "type": "string",
                      "minLength": 1,
                      "maxLength": 128,
                      "pattern": "^[A-Za-z0-9_.:/-]+$"
                    },
                    "line": {
                      "type": "integer",
                      "minimum": 0,
                      "maximum": 9007199254740991
                    }
                  },
                  "required": [
                    "module",
                    "function",
                    "line"
                  ],
                  "additionalProperties": false
                },
                "maxItems": 32
              },
              "dependency_id": {
                "type": "string",
                "minLength": 1,
                "maxLength": 128,
                "pattern": "^[A-Za-z0-9_.:/-]+$"
              },
              "wait_started_ms": {
                "type": "number",
                "minimum": 0,
                "maximum": 9007199254740991
              },
              "deadline_ms": {
                "type": "number",
                "minimum": 0,
                "maximum": 9007199254740991
              },
              "initiator": {
                "type": "string",
                "minLength": 1,
                "maxLength": 128,
                "pattern": "^[A-Za-z0-9_.:/-]+$"
              },
              "cause_event_id": {
                "type": "string",
                "minLength": 1,
                "maxLength": 128,
                "pattern": "^[A-Za-z0-9_.:/-]+$"
              },
              "duration_ms": {
                "type": "number",
                "minimum": 0,
                "maximum": 9007199254740991
              },
              "part_index": {
                "type": "integer",
                "minimum": 0,
                "maximum": 9007199254740991
              },
              "part_count": {
                "type": "integer",
                "minimum": 1,
                "maximum": 9007199254740991
              },
              "state_before": {
                "type": "string",
                "minLength": 1,
                "maxLength": 128,
                "pattern": "^[A-Za-z0-9_.:/-]+$"
              },
              "state_after": {
                "type": "string",
                "minLength": 1,
                "maxLength": 128,
                "pattern": "^[A-Za-z0-9_.:/-]+$"
              },
              "queue_depth": {
                "type": "integer",
                "minimum": 0,
                "maximum": 9007199254740991
              },
              "cursor": {
                "type": "integer",
                "minimum": 0,
                "maximum": 9007199254740991
              }
            },
            "required": [
              "site"
            ],
            "additionalProperties": false
          }
        }
      }
    },
    {
      "if": {
        "properties": {
          "event_name": {
            "const": "presentation.position"
          }
        },
        "required": [
          "event_name"
        ]
      },
      "then": {
        "properties": {
          "data": {
            "type": "object",
            "properties": {
              "site": {
                "type": "string",
                "minLength": 1,
                "maxLength": 128,
                "pattern": "^[A-Za-z0-9_.:/-]+$"
              },
              "failure_kind": {
                "type": "string",
                "minLength": 1,
                "maxLength": 128,
                "pattern": "^[A-Za-z0-9_.:/-]+$"
              },
              "condition": {
                "type": "string",
                "minLength": 1,
                "maxLength": 128,
                "pattern": "^[A-Za-z0-9_.:/-]+$"
              },
              "expected": {
                "anyOf": [
                  {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 128,
                    "pattern": "^[A-Za-z0-9_.:/-]+$"
                  },
                  {
                    "type": "boolean"
                  },
                  {
                    "type": "number",
                    "minimum": -9007199254740991,
                    "maximum": 9007199254740991
                  },
                  {
                    "type": "null"
                  }
                ]
              },
              "actual": {
                "anyOf": [
                  {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 128,
                    "pattern": "^[A-Za-z0-9_.:/-]+$"
                  },
                  {
                    "type": "boolean"
                  },
                  {
                    "type": "number",
                    "minimum": -9007199254740991,
                    "maximum": 9007199254740991
                  },
                  {
                    "type": "null"
                  }
                ]
              },
              "origin_event_id": {
                "type": "string",
                "minLength": 1,
                "maxLength": 128,
                "pattern": "^[A-Za-z0-9_.:/-]+$"
              },
              "exception_type": {
                "type": "string",
                "minLength": 1,
                "maxLength": 128,
                "pattern": "^[A-Za-z0-9_.:/-]+$"
              },
              "frames": {
                "type": "array",
                "items": {
                  "type": "object",
                  "properties": {
                    "module": {
                      "type": "string",
                      "minLength": 1,
                      "maxLength": 128,
                      "pattern": "^[A-Za-z0-9_.:/-]+$"
                    },
                    "function": {
                      "type": "string",
                      "minLength": 1,
                      "maxLength": 128,
                      "pattern": "^[A-Za-z0-9_.:/-]+$"
                    },
                    "line": {
                      "type": "integer",
                      "minimum": 0,
                      "maximum": 9007199254740991
                    }
                  },
                  "required": [
                    "module",
                    "function",
                    "line"
                  ],
                  "additionalProperties": false
                },
                "maxItems": 32
              },
              "dependency_id": {
                "type": "string",
                "minLength": 1,
                "maxLength": 128,
                "pattern": "^[A-Za-z0-9_.:/-]+$"
              },
              "wait_started_ms": {
                "type": "number",
                "minimum": 0,
                "maximum": 9007199254740991
              },
              "deadline_ms": {
                "type": "number",
                "minimum": 0,
                "maximum": 9007199254740991
              },
              "initiator": {
                "type": "string",
                "minLength": 1,
                "maxLength": 128,
                "pattern": "^[A-Za-z0-9_.:/-]+$"
              },
              "cause_event_id": {
                "type": "string",
                "minLength": 1,
                "maxLength": 128,
                "pattern": "^[A-Za-z0-9_.:/-]+$"
              },
              "duration_ms": {
                "type": "number",
                "minimum": 0,
                "maximum": 9007199254740991
              },
              "part_index": {
                "type": "integer",
                "minimum": 0,
                "maximum": 9007199254740991
              },
              "part_count": {
                "type": "integer",
                "minimum": 1,
                "maximum": 9007199254740991
              },
              "observation": {
                "enum": [
                  "prepared",
                  "play_issued",
                  "decoded",
                  "surface_submitted",
                  "frame_rendered",
                  "clock_sample",
                  "unavailable",
                  "audio_queued",
                  "audio_output"
                ]
              },
              "chunk_index": {
                "type": "integer",
                "minimum": 0,
                "maximum": 9007199254740991
              },
              "frame_index": {
                "type": "integer",
                "minimum": 0,
                "maximum": 9007199254740991
              },
              "seconds": {
                "type": "number",
                "minimum": 0,
                "maximum": 9007199254740991
              },
              "playing": {
                "type": "boolean"
              },
              "reason": {
                "type": "string",
                "minLength": 1,
                "maxLength": 128,
                "pattern": "^[A-Za-z0-9_.:/-]+$"
              }
            },
            "required": [
              "site",
              "observation"
            ],
            "additionalProperties": false
          }
        }
      }
    },
    {
      "if": {
        "properties": {
          "event_name": {
            "const": "transport.exchange"
          }
        },
        "required": [
          "event_name"
        ]
      },
      "then": {
        "properties": {
          "data": {
            "type": "object",
            "properties": {
              "site": {
                "type": "string",
                "minLength": 1,
                "maxLength": 128,
                "pattern": "^[A-Za-z0-9_.:/-]+$"
              },
              "failure_kind": {
                "type": "string",
                "minLength": 1,
                "maxLength": 128,
                "pattern": "^[A-Za-z0-9_.:/-]+$"
              },
              "condition": {
                "type": "string",
                "minLength": 1,
                "maxLength": 128,
                "pattern": "^[A-Za-z0-9_.:/-]+$"
              },
              "expected": {
                "anyOf": [
                  {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 128,
                    "pattern": "^[A-Za-z0-9_.:/-]+$"
                  },
                  {
                    "type": "boolean"
                  },
                  {
                    "type": "number",
                    "minimum": -9007199254740991,
                    "maximum": 9007199254740991
                  },
                  {
                    "type": "null"
                  }
                ]
              },
              "actual": {
                "anyOf": [
                  {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 128,
                    "pattern": "^[A-Za-z0-9_.:/-]+$"
                  },
                  {
                    "type": "boolean"
                  },
                  {
                    "type": "number",
                    "minimum": -9007199254740991,
                    "maximum": 9007199254740991
                  },
                  {
                    "type": "null"
                  }
                ]
              },
              "origin_event_id": {
                "type": "string",
                "minLength": 1,
                "maxLength": 128,
                "pattern": "^[A-Za-z0-9_.:/-]+$"
              },
              "exception_type": {
                "type": "string",
                "minLength": 1,
                "maxLength": 128,
                "pattern": "^[A-Za-z0-9_.:/-]+$"
              },
              "frames": {
                "type": "array",
                "items": {
                  "type": "object",
                  "properties": {
                    "module": {
                      "type": "string",
                      "minLength": 1,
                      "maxLength": 128,
                      "pattern": "^[A-Za-z0-9_.:/-]+$"
                    },
                    "function": {
                      "type": "string",
                      "minLength": 1,
                      "maxLength": 128,
                      "pattern": "^[A-Za-z0-9_.:/-]+$"
                    },
                    "line": {
                      "type": "integer",
                      "minimum": 0,
                      "maximum": 9007199254740991
                    }
                  },
                  "required": [
                    "module",
                    "function",
                    "line"
                  ],
                  "additionalProperties": false
                },
                "maxItems": 32
              },
              "dependency_id": {
                "type": "string",
                "minLength": 1,
                "maxLength": 128,
                "pattern": "^[A-Za-z0-9_.:/-]+$"
              },
              "wait_started_ms": {
                "type": "number",
                "minimum": 0,
                "maximum": 9007199254740991
              },
              "deadline_ms": {
                "type": "number",
                "minimum": 0,
                "maximum": 9007199254740991
              },
              "initiator": {
                "type": "string",
                "minLength": 1,
                "maxLength": 128,
                "pattern": "^[A-Za-z0-9_.:/-]+$"
              },
              "cause_event_id": {
                "type": "string",
                "minLength": 1,
                "maxLength": 128,
                "pattern": "^[A-Za-z0-9_.:/-]+$"
              },
              "duration_ms": {
                "type": "number",
                "minimum": 0,
                "maximum": 9007199254740991
              },
              "part_index": {
                "type": "integer",
                "minimum": 0,
                "maximum": 9007199254740991
              },
              "part_count": {
                "type": "integer",
                "minimum": 1,
                "maximum": 9007199254740991
              },
              "request_id": {
                "type": "string",
                "minLength": 1,
                "maxLength": 128,
                "pattern": "^[A-Za-z0-9_.:/-]+$"
              },
              "transport": {
                "enum": [
                  "http",
                  "webrtc",
                  "local"
                ]
              },
              "method": {
                "type": "string",
                "minLength": 1,
                "maxLength": 128,
                "pattern": "^[A-Za-z0-9_.:/-]+$"
              },
              "status": {
                "type": "integer",
                "minimum": 0,
                "maximum": 9007199254740991
              },
              "bytes": {
                "type": "integer",
                "minimum": 0,
                "maximum": 9007199254740991
              }
            },
            "required": [
              "site",
              "request_id",
              "transport",
              "method"
            ],
            "additionalProperties": false
          }
        }
      }
    },
    {
      "if": {
        "properties": {
          "event_name": {
            "const": "diagnostics.validation_failed"
          }
        },
        "required": [
          "event_name"
        ]
      },
      "then": {
        "properties": {
          "data": {
            "type": "object",
            "properties": {
              "site": {
                "type": "string",
                "minLength": 1,
                "maxLength": 128,
                "pattern": "^[A-Za-z0-9_.:/-]+$"
              },
              "issues": {
                "type": "array",
                "minItems": 1,
                "maxItems": 32,
                "items": {
                  "type": "object",
                  "properties": {
                    "path": {
                      "type": "string",
                      "maxLength": 256
                    },
                    "rule": {
                      "type": "string",
                      "minLength": 1,
                      "maxLength": 128,
                      "pattern": "^[A-Za-z0-9_.:/-]+$"
                    }
                  },
                  "required": [
                    "path",
                    "rule"
                  ],
                  "additionalProperties": false
                }
              }
            },
            "required": [
              "site",
              "issues"
            ],
            "additionalProperties": false
          }
        }
      }
    },
    {
      "if": {
        "properties": {
          "event_name": {
            "const": "diagnostics.sink_failed"
          }
        },
        "required": [
          "event_name"
        ]
      },
      "then": {
        "properties": {
          "data": {
            "type": "object",
            "properties": {
              "site": {
                "type": "string",
                "minLength": 1,
                "maxLength": 128,
                "pattern": "^[A-Za-z0-9_.:/-]+$"
              },
              "reason": {
                "enum": [
                  "enqueue_threw",
                  "enqueue_rejected",
                  "sequence_exhausted",
                  "clock_failed",
                  "reentrant_emit",
                  "input_invalid"
                ]
              },
              "sink_stage": {
                "enum": [
                  "validate",
                  "serialize",
                  "closed",
                  "enqueue",
                  "dispatch",
                  "mkdir",
                  "stat",
                  "rotate",
                  "open",
                  "write",
                  "flush",
                  "close",
                  "post_write"
                ]
              },
              "sink_reason": {
                "enum": [
                  "queue_full",
                  "journal_closed",
                  "invalid_event",
                  "permission_denied",
                  "disk_full",
                  "io_error",
                  "other"
                ]
              },
              "errno": {
                "type": "integer",
                "minimum": 0,
                "maximum": 2147483647
              },
              "winerror": {
                "type": "integer",
                "minimum": 0,
                "maximum": 2147483647
              },
              "queue_depth": {
                "type": "integer",
                "minimum": 0,
                "maximum": 2147483647
              },
              "queue_capacity": {
                "type": "integer",
                "minimum": 0,
                "maximum": 2147483647
              },
              "related_event_id": {
                "anyOf": [
                  {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 128,
                    "pattern": "^[A-Za-z0-9_.:/-]+$"
                  },
                  {
                    "type": "null"
                  }
                ]
              }
            },
            "required": [
              "site",
              "reason",
              "related_event_id"
            ],
            "additionalProperties": false
          }
        }
      }
    },
    {
      "if": {
        "properties": {
          "event_name": {
            "const": "diagnostics.capture_state"
          }
        },
        "required": [
          "event_name"
        ]
      },
      "then": {
        "properties": {
          "data": {
            "type": "object",
            "properties": {
              "site": {
                "type": "string",
                "minLength": 1,
                "maxLength": 128,
                "pattern": "^[A-Za-z0-9_.:/-]+$"
              },
              "state": {
                "enum": [
                  "starting",
                  "active",
                  "stopped",
                  "incomplete",
                  "outstanding"
                ]
              },
              "reason": {
                "type": "string",
                "minLength": 1,
                "maxLength": 128,
                "pattern": "^[A-Za-z0-9_.:/-]+$"
              },
              "dropped_count": {
                "type": "integer",
                "minimum": 0,
                "maximum": 9007199254740991
              },
              "outstanding_operations": {
                "type": "array",
                "items": {
                  "type": "string",
                  "minLength": 1,
                  "maxLength": 128,
                  "pattern": "^[A-Za-z0-9_.:/-]+$"
                },
                "maxItems": 64
              }
            },
            "required": [
              "site",
              "state"
            ],
            "additionalProperties": false
          }
        }
      }
    },
    {
      "if": {
        "properties": {
          "event_name": {
            "const": "relay.transition"
          }
        },
        "required": [
          "event_name"
        ]
      },
      "then": {
        "properties": {
          "data": {
            "type": "object",
            "properties": {
              "site": {
                "const": "relay.transition"
              },
              "trigger": {
                "enum": [
                  "socket_closed",
                  "signaling_error",
                  "peer_disconnected",
                  "peer_failed",
                  "data_channel_closed",
                  "authorization_expired",
                  "authorization_rejected",
                  "explicit_cleanup",
                  "reconnect_scheduled",
                  "peer_recovered",
                  "recovery_timeout",
                  "desktop_changed",
                  "peer_connecting",
                  "peer_connected",
                  "ice_state_changed",
                  "candidate_selected"
                ]
              },
              "initiator": {
                "enum": [
                  "signaling",
                  "peer",
                  "data_channel",
                  "authorization",
                  "application",
                  "timer",
                  "ice"
                ]
              },
              "event_role": {
                "enum": [
                  "initiating",
                  "cleanup",
                  "retry"
                ]
              },
              "peer_state": {
                "enum": [
                  "none",
                  "new",
                  "connecting",
                  "connected",
                  "disconnected",
                  "failed",
                  "closed",
                  "unknown"
                ]
              },
              "ice_state": {
                "enum": [
                  "none",
                  "new",
                  "connecting",
                  "connected",
                  "disconnected",
                  "failed",
                  "closed",
                  "unknown",
                  "checking",
                  "completed"
                ]
              },
              "channel_state": {
                "enum": [
                  "none",
                  "connecting",
                  "open",
                  "closing",
                  "closed",
                  "unknown"
                ]
              },
              "signaling_state": {
                "enum": [
                  "none",
                  "connecting",
                  "open",
                  "closing",
                  "closed",
                  "unknown"
                ]
              },
              "authorization_valid": {
                "type": "boolean"
              },
              "authorization_remaining_ms": {
                "anyOf": [
                  {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 9007199254740991
                  },
                  {
                    "type": "null"
                  }
                ]
              },
              "pending_commands": {
                "type": "integer",
                "minimum": 0,
                "maximum": 10000
              },
              "selected_candidate_type": {
                "enum": [
                  "host",
                  "srflx",
                  "prflx",
                  "relay",
                  "unknown"
                ]
              },
              "candidate_protocol": {
                "enum": [
                  "udp",
                  "tcp",
                  "unknown"
                ]
              },
              "cause_event_id": {
                "anyOf": [
                  {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 128,
                    "pattern": "^[A-Za-z0-9_.:/-]+$"
                  },
                  {
                    "type": "null"
                  }
                ]
              }
            },
            "required": [
              "site",
              "trigger",
              "initiator",
              "event_role",
              "peer_state",
              "ice_state",
              "channel_state",
              "signaling_state",
              "authorization_valid",
              "authorization_remaining_ms",
              "pending_commands",
              "selected_candidate_type",
              "candidate_protocol"
            ],
            "additionalProperties": false
          }
        }
      }
    },
    {
      "if": {
        "properties": {
          "phase": {
            "const": "begin"
          }
        },
        "required": [
          "phase"
        ]
      },
      "then": {
        "properties": {
          "outcome": {
            "enum": [
              "pending"
            ]
          }
        }
      }
    },
    {
      "if": {
        "properties": {
          "phase": {
            "const": "decision"
          }
        },
        "required": [
          "phase"
        ]
      },
      "then": {
        "properties": {
          "outcome": {
            "enum": [
              "observed"
            ]
          }
        }
      }
    },
    {
      "if": {
        "properties": {
          "phase": {
            "const": "wait"
          }
        },
        "required": [
          "phase"
        ]
      },
      "then": {
        "properties": {
          "outcome": {
            "enum": [
              "pending"
            ]
          }
        }
      }
    },
    {
      "if": {
        "properties": {
          "phase": {
            "const": "progress"
          }
        },
        "required": [
          "phase"
        ]
      },
      "then": {
        "properties": {
          "outcome": {
            "enum": [
              "observed"
            ]
          }
        }
      }
    },
    {
      "if": {
        "properties": {
          "phase": {
            "const": "snapshot"
          }
        },
        "required": [
          "phase"
        ]
      },
      "then": {
        "properties": {
          "outcome": {
            "enum": [
              "observed"
            ]
          }
        }
      }
    },
    {
      "if": {
        "properties": {
          "phase": {
            "const": "end"
          }
        },
        "required": [
          "phase"
        ]
      },
      "then": {
        "properties": {
          "outcome": {
            "enum": [
              "success",
              "rejected",
              "cancelled",
              "failed"
            ]
          }
        }
      }
    },
    {
      "if": {
        "properties": {
          "build_id": {
            "const": null
          }
        },
        "required": [
          "build_id"
        ]
      },
      "then": {
        "properties": {
          "build_unavailable_reason": {
            "type": "string",
            "minLength": 1,
            "maxLength": 128,
            "pattern": "^[A-Za-z0-9_.:/-]+$"
          }
        }
      }
    },
    {
      "if": {
        "properties": {
          "build_id": {
            "type": "string"
          }
        }
      },
      "then": {
        "properties": {
          "build_unavailable_reason": {
            "type": "null"
          }
        }
      }
    },
    {
      "if": {
        "properties": {
          "outcome": {
            "const": "failed"
          }
        },
        "required": [
          "outcome"
        ]
      },
      "then": {
        "properties": {
          "data": {
            "required": [
              "failure_kind",
              "site",
              "condition",
              "expected",
              "actual",
              "origin_event_id"
            ]
          }
        }
      }
    },
    {
      "if": {
        "properties": {
          "outcome": {
            "const": "rejected"
          }
        },
        "required": [
          "outcome"
        ]
      },
      "then": {
        "properties": {
          "data": {
            "required": [
              "failure_kind",
              "site",
              "condition",
              "expected",
              "actual",
              "origin_event_id"
            ]
          }
        }
      }
    },
    {
      "if": {
        "properties": {
          "phase": {
            "const": "wait"
          }
        },
        "required": [
          "phase"
        ]
      },
      "then": {
        "properties": {
          "data": {
            "required": [
              "site",
              "dependency_id",
              "condition",
              "wait_started_ms",
              "deadline_ms"
            ]
          }
        }
      }
    },
    {
      "if": {
        "properties": {
          "outcome": {
            "const": "cancelled"
          }
        },
        "required": [
          "outcome"
        ]
      },
      "then": {
        "properties": {
          "data": {
            "required": [
              "site",
              "initiator",
              "cause_event_id"
            ]
          }
        }
      }
    }
  ],
  "x-maxUtf8Bytes": 16384
} as const;
