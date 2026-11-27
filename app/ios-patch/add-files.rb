# Adds GoogleService-Info.plist (if present) and the push entitlements file to the Xcode project.
require 'xcodeproj'
proj = Xcodeproj::Project.open('ios/App/App.xcodeproj')
t = proj.targets.find { |x| x.name == 'App' }
grp = proj.main_group['App']
if File.exist?('ios/App/App/GoogleService-Info.plist') && !grp.files.any? { |f| f.path == 'GoogleService-Info.plist' }
  ref = grp.new_reference('GoogleService-Info.plist'); t.resources_build_phase.add_file_reference(ref)
  puts 'Added GoogleService-Info.plist'
end
grp.new_reference('App.entitlements') unless grp.files.any? { |f| f.path == 'App.entitlements' }
t.build_configurations.each { |c| c.build_settings['CODE_SIGN_ENTITLEMENTS'] = 'App/App.entitlements' }
proj.save
