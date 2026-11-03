require 'json'

package = JSON.parse(File.read(File.join(__dir__, '..', 'package.json')))

Pod::Spec.new do |s|
  s.name = 'NcLiveCapture'
  s.version = package['version']
  s.summary = 'Continuous iOS microphone capture for NeuralCompanion.'
  s.description = s.summary
  s.license = { :type => 'Proprietary' }
  s.author = 'NeuralCompanion'
  s.homepage = 'file://.'
  s.platforms = { :ios => '15.1' }
  s.swift_version = '5.9'
  s.source = { :path => '.' }
  s.static_framework = true

  s.dependency 'ExpoModulesCore'
  s.dependency 'ExpoAudio'
  s.source_files = '*.{swift,h,c}'
  s.public_header_files = 'CaptureRing.h'
  s.pod_target_xcconfig = {
    'DEFINES_MODULE' => 'YES',
    'CLANG_C_LANGUAGE_STANDARD' => 'c11'
  }
end
