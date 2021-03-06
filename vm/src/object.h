// Copyright 2014 Jay Conrod. All rights reserved.

// This file is part of CodeSwitch. Use of this source code is governed by
// the 3-clause BSD license that can be found in the LICENSE.txt file.


#ifndef object_h
#define object_h

#include <iostream>
#include "block.h"

namespace codeswitch {
namespace internal {

class Object: public Block {
 public:
  static const BlockType kBlockType = OBJECT_BLOCK_TYPE;

  void* operator new (size_t, Heap* heap, Meta* meta);
  void* operator new (size_t, Heap* heap, Meta* meta, length_t length);
  Object();
  static Local<Object> create(Heap* heap, const Handle<Meta>& meta);
  static Local<Object> create(Heap* heap, const Handle<Meta>& meta, length_t length);

 protected:
  explicit Object(BlockType blockType);
};

std::ostream& operator << (std::ostream& os, const Object* obj);

}
}

#endif
