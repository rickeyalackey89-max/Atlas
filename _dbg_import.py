import os 
import Atlas.core.slip_builders as sb 
print('ENV_ATLAS_DEBUG_BUILDER=', os.getenv('ATLAS_DEBUG_BUILDER')) 
print('SLIP_BUILDERS_FILE=', sb.__file__) 
