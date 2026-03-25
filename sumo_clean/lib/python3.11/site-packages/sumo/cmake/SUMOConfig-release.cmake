#----------------------------------------------------------------
# Generated CMake target import file for configuration "Release".
#----------------------------------------------------------------

# Commands may need to know the format version.
set(CMAKE_IMPORT_FILE_VERSION 1)

# Import target "SUMO::libsumocpp" for configuration "Release"
set_property(TARGET SUMO::libsumocpp APPEND PROPERTY IMPORTED_CONFIGURATIONS RELEASE)
set_target_properties(SUMO::libsumocpp PROPERTIES
  IMPORTED_LOCATION_RELEASE "${_IMPORT_PREFIX}/lib/libsumocpp.dylib"
  IMPORTED_SONAME_RELEASE "@rpath/libsumocpp.dylib"
  )

list(APPEND _cmake_import_check_targets SUMO::libsumocpp )
list(APPEND _cmake_import_check_files_for_SUMO::libsumocpp "${_IMPORT_PREFIX}/lib/libsumocpp.dylib" )

# Import target "SUMO::libtracicpp" for configuration "Release"
set_property(TARGET SUMO::libtracicpp APPEND PROPERTY IMPORTED_CONFIGURATIONS RELEASE)
set_target_properties(SUMO::libtracicpp PROPERTIES
  IMPORTED_LOCATION_RELEASE "${_IMPORT_PREFIX}/lib/libtracicpp.dylib"
  IMPORTED_SONAME_RELEASE "@rpath/libtracicpp.dylib"
  )

list(APPEND _cmake_import_check_targets SUMO::libtracicpp )
list(APPEND _cmake_import_check_files_for_SUMO::libtracicpp "${_IMPORT_PREFIX}/lib/libtracicpp.dylib" )

# Commands beyond this point should not need to know the version.
set(CMAKE_IMPORT_FILE_VERSION)
