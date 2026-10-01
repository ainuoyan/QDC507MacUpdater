# SPDX-License-Identifier: GPL-3.0-only
import logging
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET
import usb.core

sys.path.insert(0, str(Path(__file__).parent / 'vendor/edl'))
from edlclient.Library.firehose import firehose, response
from edlclient.Library.Connection.usblib import usb_class


class NandProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.image = Path(self.temp.name) / 'RAWDATA.bin'
        self.image.write_bytes(b'x' * 8192)
        self.fh = object.__new__(firehose)
        self.fh.cfg = SimpleNamespace(MemoryName='nand', PAGES_PER_BLOCK=64,
                                      SECTOR_SIZE_IN_BYTES=2048, MaxPayloadSizeToTargetInBytes=4096)
        self.fh.modules = None
        self.fh.skipresponse = False
        self.fh.loglevel = logging.ERROR
        self.fh.info = Mock()
        self.fh.error = Mock()
        self.fh.cdc = SimpleNamespace(write=Mock(return_value=True))
        self.fh.xmlsend = Mock(return_value=response(resp=True))
        self.fh.wait_for_data = Mock(return_value=b'')
        self.fh.xml = SimpleNamespace(getlog=Mock(return_value=[]),
                                      getresponse=Mock(return_value={'value': 'ACK'}))

    def tearDown(self):
        self.temp.cleanup()

    def test_program_has_bounded_end_and_exact_bytes(self):
        self.assertTrue(self.fh.cmd_program(0, 11648, str(self.image), display=False))
        tag = ET.fromstring(self.fh.xmlsend.call_args[0][0]).find('program')
        self.assertEqual(tag.attrib['last_sector'], '11651')
        self.assertEqual(tag.attrib['num_partition_sectors'], '4')
        self.assertEqual(tag.attrib['PAGES_PER_BLOCK'], '64')
        payload = b''.join(call.args[0] for call in self.fh.cdc.write.call_args_list)
        self.assertEqual(payload, self.image.read_bytes())

    def test_rejected_program_never_sends_payload(self):
        self.fh.xmlsend.return_value = response(resp=False, error='NAK')
        self.assertFalse(self.fh.cmd_program(0, 11648, str(self.image), display=False))
        self.fh.cdc.write.assert_not_called()

    def test_usb_failure_stops_payload(self):
        self.fh.cdc.write.return_value = False
        self.assertFalse(self.fh.cmd_program(0, 11648, str(self.image), display=False))
        self.assertEqual(self.fh.cdc.write.call_count, 1)

    def test_erase_has_bounded_end(self):
        self.fh.supported_functions = ['erase']
        self.assertTrue(self.fh.cmd_erase(0, 11648, 256, display=False))
        tag = ET.fromstring(self.fh.xmlsend.call_args[0][0]).find('erase')
        self.assertEqual(tag.attrib['last_sector'], '11903')

    def test_usb_short_transfer_is_failure(self):
        usb = SimpleNamespace(EP_OUT=SimpleNamespace(write=Mock(return_value=2)),
                              error=Mock(), debug=Mock(), verify_data=Mock())
        self.assertFalse(usb_class.write(usb, b'abcd', pktsize=4))

    def test_usb_exception_never_replays_payload(self):
        endpoint = Mock(side_effect=[usb.core.USBError('interrupted transfer'), 4])
        transport = SimpleNamespace(EP_OUT=SimpleNamespace(write=endpoint),
                              error=Mock(), debug=Mock(), verify_data=Mock())
        self.assertFalse(usb_class.write(transport, b'abcd', pktsize=4))
        self.assertEqual(endpoint.call_count, 1)

    def test_failed_zero_length_transfer_stops_program(self):
        self.fh.cdc.write.side_effect = lambda data: bool(data)
        self.assertFalse(self.fh.cmd_program(0, 11648, str(self.image), display=False))
        self.assertEqual(self.fh.cdc.write.call_count, 2)

    def test_nand_requires_native_erase(self):
        self.fh.supported_functions = []
        self.assertFalse(self.fh.cmd_erase(0, 11648, 256, display=False))
        self.fh.xmlsend.assert_not_called()
        self.fh.cdc.write.assert_not_called()

    def test_empty_response_is_not_ack(self):
        self.assertFalse(self.fh.getstatus({}))

    def test_xml_write_failure_never_reads_response(self):
        self.fh.cdc = SimpleNamespace(flush=Mock(), write=Mock(return_value=False),
                                     read=Mock(), xmlread=False)
        self.fh.cfg.MaxXMLSizeInBytes = 4096
        self.assertFalse(firehose.xmlsend(self.fh, '<data/>').resp)
        self.fh.cdc.read.assert_not_called()

    def test_oversized_xml_is_rejected_without_truncation(self):
        self.fh.cdc = SimpleNamespace(flush=Mock(), write=Mock(), read=Mock(), xmlread=False)
        self.fh.cfg.MaxXMLSizeInBytes = 4
        self.assertFalse(firehose.xmlsend(self.fh, '<data/>').resp)
        self.fh.cdc.write.assert_not_called()

    def test_read_nak_is_failure(self):
        target = self.prepare_read([b'x' * 2048], {'value': 'NAK'})
        self.assertFalse(self.fh.cmd_read(0, 0, 1, str(target), display=False))

    def test_nand_erase_nak_stops(self):
        self.fh.supported_functions = ['erase']
        self.fh.xmlsend.return_value = response(resp=False, error='NAK')
        self.assertFalse(self.fh.cmd_erase(0, 11648, 256, display=False))
        self.fh.cdc.write.assert_not_called()

    def prepare_read(self, payload, response_value):
        self.fh.cfg.MaxPayloadSizeFromTargetInBytes = 4096
        self.fh.cdc = SimpleNamespace(is_serial=False, xmlread=True, read=Mock(side_effect=payload))
        self.fh.xml.getresponse.return_value = response_value
        return Path(self.temp.name) / 'readback.bin'

    def test_read_without_final_ack_is_failure(self):
        target = self.prepare_read([b'x' * 2048], {})
        self.assertFalse(self.fh.cmd_read(0, 0, 1, str(target), display=False))

    def test_read_empty_usb_expires_and_restores_xml_mode(self):
        target = self.prepare_read([b''], {'value': 'ACK'})
        self.fh.cdc.read.side_effect = None
        self.fh.cdc.read.return_value = b''
        with patch('edlclient.Library.firehose.time.monotonic', side_effect=[0, 31]), \
             patch('edlclient.Library.firehose.time.sleep'):
            self.assertFalse(self.fh.cmd_read(0, 0, 1, str(target), display=False))
        self.assertTrue(self.fh.cdc.xmlread)

    def test_read_disk_error_is_failure(self):
        target = self.prepare_read([b'x' * 2048], {'value': 'ACK'})
        with patch('builtins.open', side_effect=OSError('disk full')):
            self.assertFalse(self.fh.cmd_read(0, 0, 1, str(target), display=False))
        self.assertTrue(self.fh.cdc.xmlread)

    def test_successful_read_writes_exact_bytes(self):
        target = self.prepare_read([b'a' * 1024, b'b' * 1024], {'value': 'ACK'})
        self.assertTrue(self.fh.cmd_read(0, 0, 1, str(target), display=False))
        self.assertEqual(target.read_bytes(), b'a' * 1024 + b'b' * 1024)
        self.assertTrue(self.fh.cdc.xmlread)


if __name__ == '__main__':
    unittest.main()
