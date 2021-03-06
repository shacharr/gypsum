# Copyright 2014-2015, Jay Conrod. All rights reserved.
#
# This file is part of Gypsum. Use of this source code is governed by
# the GPL license that can be found in the LICENSE.txt file.


import copy

import builtins
import bytecode
import data
import errors
import flags
import ir_values
import utils

NULLABLE_TYPE_FLAG = "nullable"

class Type(data.Data):
    propertyNames = ("flags",)

    def __init__(self, flags=None):
        if flags is None:
            flags = frozenset()
        if isinstance(flags, str):
            flags = frozenset([flags])
        assert isinstance(flags, frozenset)
        self.flags = flags

    def withFlag(self, flag):
        ty = copy.copy(self)
        ty.flags |= frozenset((flag,))
        return ty

    def withoutFlag(self, flag):
        ty = copy.copy(self)
        ty.flags -= frozenset((flag,))
        return ty

    def isSubtypeOf(self, other):
        if self == other:
            return True
        elif isinstance(self, VariableType) and \
             isinstance(other, VariableType) and \
             self.typeParameter.hasCommonBound(other.typeParameter):
            return True
        elif isinstance(self, VariableType):
            return self.typeParameter.upperBound.isSubtypeOf(other)
        elif isinstance(other, VariableType):
            return self.isSubtypeOf(other.typeParameter.lowerBound)
        elif isinstance(self, ClassType) and \
             isinstance(other, ClassType) and \
             (not self.isNullable() or other.isNullable()):
            if self.clas is builtins.getNothingClass():
                return True
            else:
                return self.isSubtypeOfWithVariance(other, BIVARIANT)
        else:
            return False

    def isPrimitive(self):
        raise NotImplementedError

    def isObject(self):
        raise NotImplementedError

    def combine(self, ty, loc):
        if self == ty:
            return self
        elif self is NoType:
            return ty
        elif ty is NoType:
            return self
        elif isinstance(self, ClassType) and isinstance(ty, ClassType):
            commonFlags = self.combineFlags(ty)
            if self.clas is builtins.getNothingClass():
                return ClassType(ty.clas, ty.typeArguments, commonFlags)
            elif ty.clas is builtins.getNothingClass():
                return ClassType(self.clas, self.typeArguments, commonFlags)
            commonBase = self.clas.findCommonBaseClass(ty.clas)
            selfTypeArgs = self.substituteForBaseClass(commonBase).typeArguments
            otherTypeArgs = ty.substituteForBaseClass(commonBase).typeArguments
            if selfTypeArgs != otherTypeArgs:
                # TODO: support co/contra-variance
                raise errors.TypeException(loc, "could not combine; incompatible type args")
            return ClassType(commonBase, selfTypeArgs, commonFlags)
        else:
            raise errors.TypeException(loc, "could not combine")

    def combineFlags(self, other):
        return self.flags.union(other.flags)

    def substitute(self, parameters, replacements):
        raise NotImplementedError

    def substituteForInheritance(self, clas, base):
        assert clas.isSubclassOf(base)
        supertypePath = clas.findTypePathToBaseClass(base)
        ty = self
        for sty in reversed(supertypePath):
            ty = ty.substitute(sty.clas.typeParameters, sty.typeArguments)
        return ty

    def getTypeArguments(self):
        raise NotImplementedError

    def size(self):
        raise NotImplementedError

    def alignment(self):
        return self.size()

    def defaultValue(self):
        return None

    def isNullable(self):
        raise NotImplementedError


class SimpleType(Type):
    propertyNames = Type.propertyNames + ("name", "width")

    def __init__(self, name, width, defaultValue=None):
        super(SimpleType, self).__init__(frozenset())
        self.name = name
        self.width = width
        self.defaultValue_ = defaultValue

    def __repr__(self):
        return self.name

    def __str__(self):
        return self.name

    def substitute(self, parameters, replacements):
        return self

    def isPrimitive(self):
        return True

    def isObject(self):
        return False

    def size(self):
        widthSizes = { bytecode.W8: 1, bytecode.W16: 2, bytecode.W32: 4, bytecode.W64: 8 }
        return widthSizes[self.width]

    def defaultValue(self):
        return self.defaultValue_

    def getTypeArguments(self):
        return ()

    def isNullable(self):
        assert NULLABLE_TYPE_FLAG not in self.flags
        return False


NoType = SimpleType("_", None)
UnitType = SimpleType("unit", bytecode.W8, ir_values.UnitValue())
I8Type = SimpleType("i8", bytecode.W8, ir_values.I8Value(0))
I16Type = SimpleType("i16", bytecode.W16, ir_values.I16Value(0))
I32Type = SimpleType("i32", bytecode.W32, ir_values.I32Value(0))
I64Type = SimpleType("i64", bytecode.W64, ir_values.I64Value(0))
F32Type = SimpleType("f32", bytecode.W32, ir_values.F32Value(0.))
F64Type = SimpleType("f64", bytecode.W64, ir_values.F64Value(0.))
BooleanType = SimpleType("boolean", bytecode.W8, ir_values.BooleanValue(False))


class ObjectType(Type):
    def __init__(self, flags):
        super(ObjectType, self).__init__(flags)

    def isPrimitive(self):
        return False

    def isObject(self):
        return True

    def size(self):
        return bytecode.WORDSIZE

    def substituteForBaseClass(self, base):
        """Returns a base type of the corresponding class with type arguments substituted
        appropriately. For example, if we have class A[T] and class B <: A[C], then if we
        call this method on B, we will get A[C]. Note that this goes in the reverse direction
        from `substituteForInheritance`."""
        raise NotImplementedError


class ClassType(ObjectType):
    propertyNames = Type.propertyNames + ("clas", "typeArguments")
    width = bytecode.WORD

    def __init__(self, clas, typeArguments=(), flags=None):
        super(ClassType, self).__init__(flags)
        self.clas = clas
        self.typeArguments = typeArguments

    @staticmethod
    def forReceiver(clas):
        typeArgs = tuple(VariableType(t) for t in clas.typeParameters)
        return ClassType(clas, typeArgs, None)

    def __str__(self):
        if len(self.typeArguments) == 0:
            return self.clas.name
        else:
            return "%s[%s]%s" % \
                   (self.clas.name,
                    ",".join(map(str, self.typeArguments)),
                    "?" if self.isNullable() else "")

    def __repr__(self):
        typeArgsStr = (", (" + ", ".join(map(repr, self.typeArguments)) + ")") \
                      if len(self.typeArguments) > 0 \
                      else ""
        flagsStr = (", " + ", ".join(self.flags)) if len(self.flags) > 0 else ""
        return "ClassType(%s%s%s)" % (self.clas.name, typeArgsStr, flagsStr)

    def __hash__(self):
        return utils.hashList([getattr(self, name) for name in Type.propertyNames] + \
                        [self.clas.name, self.typeArguments])

    def __eq__(self, other):
        return self.__class__ is other.__class__ and \
               self.flags == other.flags and \
               self.clas is other.clas and \
               self.typeArguments == other.typeArguments

    def isSubtypeOfWithVariance(self, other, variance):
        if self.clas is builtins.getNothingClass():
            return True
        if not self.clas.isSubclassOf(other.clas):
            return False
        selfTypeArgs = self.substituteForBaseClass(other.clas).typeArguments
        otherTypeArgs = other.typeArguments
        typeParams = other.clas.typeParameters
        assert len(selfTypeArgs) == len(otherTypeArgs)

        def checkArg(a, b, param):
            argVariance = changeVariance(variance, param.variance())
            if argVariance is flags.COVARIANT:
                return a.isSubtypeOfWithVariance(b, argVariance)
            elif argVariance is flags.CONTRAVARIANT:
                return b.isSubtypeOfWithVariance(a, argVariance)
            else:
                assert argVariance is INVARIANT
                return a == b

        return all(checkArg(a, b, param) for a, b, param in
                   zip(selfTypeArgs, otherTypeArgs, typeParams))

    def substitute(self, parameters, replacements):
        return ClassType(self.clas,
                         tuple(arg.substitute(parameters, replacements)
                               for arg in self.typeArguments),
                         self.flags)

    def substituteForBaseClass(self, base):
        assert base is not builtins.getNothingClass()
        assert self.clas is not builtins.getNothingClass()
        supertypePath = self.clas.findTypePathToBaseClass(base)
        ty = self
        for sty in supertypePath:
            ty = sty.substitute(ty.clas.typeParameters, ty.typeArguments)
        return ty

    def getTypeArguments(self):
        return self.typeArguments

    def isNullable(self):
        return NULLABLE_TYPE_FLAG in self.flags



class VariableType(ObjectType):
    propertyNames = Type.propertyNames + ("typeParameter",)
    width = bytecode.WORD

    def __init__(self, typeParameter):
        super(VariableType, self).__init__(frozenset())
        self.typeParameter = typeParameter

    def __str__(self):
        return self.typeParameter.name

    def __repr__(self):
        return "VariableType(%s)" % self.typeParameter.name

    def __hash__(self):
        return utils.hashList([self.typeParameter.name])

    def __eq__(self, other):
        return self.__class__ is other.__class__ and \
               self.typeParameter is other.typeParameter

    def substitute(self, parameters, replacements):
        assert len(parameters) == len(replacements)
        for param, repl in zip(parameters, replacements):
            if param is self.typeParameter:
                return repl
        return self

    def getTypeArguments(self):
        if self.typeParameter.upperBound is not None:
            return self.typeParameter.upperBound.getTypeArguments()
        else:
            return ()

    def isNullable(self):
        return self.typeParameter.upperBound is not None and \
               self.typeParameter.upperBound.isNullable()

    def substituteForBaseClass(self, base):
        return self.typeParameter.upperBound.substituteForBaseClass(base)


def getClassFromType(ty):
    if isinstance(ty, ClassType):
        return ty.clas
    elif isinstance(ty, VariableType):
        return getClassFromType(ty.typeParameter.upperBound)
    else:
        assert ty.isPrimitive()
        return builtins.getBuiltinClassFromType(ty)


def getRootClassType():
    return ClassType(builtins.getRootClass(), ())


def getNothingClassType():
    return ClassType(builtins.getNothingClass())


def getNullType():
    return ClassType(builtins.getNothingClass(), (), frozenset([NULLABLE_TYPE_FLAG]))


def getStringType():
    return ClassType(builtins.getStringClass())


# Extra variance symbols
# Invariant means neither covariant nor contravariant.
INVARIANT = "invariant"
# BIVARIANT means either COVARIANT or CONTRAVARIANT.
BIVARIANT = "bivariant"


def changeVariance(old, new):
    assert new is not BIVARIANT
    if old is INVARIANT:
        return INVARIANT
    elif old in [BIVARIANT, flags.COVARIANT]:
        return new
    else:
        if new is flags.CONTRAVARIANT:
            return flags.COVARIANT
        elif new is flags.COVARIANT:
            return flags.CONTRAVARIANT
        else:
            assert new is INVARIANT
            return INVARIANT

__all__ = ["BIVARIANT","INVARIANT", "UnitType", "BooleanType", "I8Type",
           "I16Type", "I32Type", "I64Type", "F32Type", "F64Type",
           "VariableType", "ClassType",  "NoType",
           "getRootClassType", "getStringType", "getNullType",
           "getClassFromType", "NULLABLE_TYPE_FLAG", "changeVariance",
           "getNothingClassType"]
