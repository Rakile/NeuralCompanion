This directory contains the unmodified QRCode vendor files from the existing
qrcode-terminal dependency in the NC phone development environment. The original
encoder is Copyright (c) 2009 Kazuhiko Arase, licensed under MIT, with Node
adaptations from qrcode-terminal. The upstream combined license and attribution
are retained in LICENSE and the source headers.

Only the local enrollment renderer uses this copy. Its input is a bounded ASCII
otpauth URI; account labels supplied by the relay are percent encoded. No QR
service, network request, native module, or new package install is required.
