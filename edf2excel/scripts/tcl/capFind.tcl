# capFind.tcl — 仅封装 Capture 内置 FindParts / FindPins / FindNets
# 多 section：FindParts U1000 失败会试 U1000A…U1000Z；FindPins U1000.J12 失败会试 U1000A.J12 …
#
#   source [file normalize {D:/03_AI/test/capFind.tcl}]
#   caploc …   caplocr …   caplocn …   caplocp …   caplcc

package require Tcl 8.4
package provide capFind 1.0

namespace eval ::capFind {
    variable _suffixLetters {A B C D E F G H I J K L M N O P Q R S T U V W X Y Z}
}

# Find* 第二参数为布尔字符串；兼容 FALSE / false
proc ::capFind::_findWithBoolArg {cmd arg} {
    if {$arg eq "" || [llength [info commands $cmd]] != 1} {
        return 0
    }
    foreach ba {FALSE false} {
        if {![catch [list $cmd $arg $ba]]} {
            return 1
        }
    }
    return 0
}

# 先精确位号；失败且形如 U1000（字母+至少3位尾数）再试 U1000A…U1000Z
proc ::capFind::findPartsCmd {refDes} {
    set r [string trim $refDes]
    if {![regexp {^[A-Za-z]+[0-9]{3,}$} $r]} {
        return [::capFind::_findWithBoolArg FindParts $r]
    }
    if {[::capFind::_findWithBoolArg FindParts $r]} {
        return 1
    }
    variable _suffixLetters
    foreach suf $_suffixLetters {
        if {[::capFind::_findWithBoolArg FindParts ${r}${suf}]} {
            return 1
        }
    }
    return 0
}

proc ::capFind::findNetsCmd {netName} {
    return [::capFind::_findWithBoolArg FindNets [string trim $netName]]
}

# 先用户原串；若失败且为「数字结尾位号 + . + 管脚」则试 U1000A.J12 … U1000Z.J12（等同常见 U1000F.J12）
proc ::capFind::findPinsCmdSmart {refDotPin} {
    set s [string trim $refDotPin]
    if {$s eq ""} {
        return 0
    }
    if {[::capFind::_findWithBoolArg FindPins $s]} {
        return 1
    }
    if {![regexp {^(.+[0-9])(\.)(.+)$} $s _ base dot tail]} {
        return 0
    }
    variable _suffixLetters
    foreach suf $_suffixLetters {
        if {[::capFind::_findWithBoolArg FindPins ${base}${suf}${dot}${tail}]} {
            return 1
        }
    }
    return 0
}

proc ::capFind::cleanupLastPage {} {
    catch {UnSelectAll}
}

# 去掉用户误传的第二参数（与 Tcl 里 Find* 的 FALSE 混淆）
proc ::capFind::normalizeLocateArg {s} {
    set t [string trim $s]
    if {[regexp -nocase {^(.+)\s+false$} $t _ a]} {
        return [string trim $a]
    }
    return $t
}

proc ::capFind::locateByRefDes {refDes {quietNotFound 0}} {
    set refDes [::capFind::normalizeLocateArg $refDes]
    ::capFind::cleanupLastPage
    if {[::capFind::findPartsCmd $refDes]} {
        return 1
    }
    if {!$quietNotFound} {
        puts "capFind: FindParts failed or no match: $refDes"
    }
    return 0
}

proc ::capFind::locateByNet {netName} {
    set netName [::capFind::normalizeLocateArg $netName]
    ::capFind::cleanupLastPage
    if {[::capFind::findNetsCmd $netName]} {
        return
    }
    puts "capFind: FindNets failed or no match: $netName"
}

proc ::capFind::locateByPin {pinPath} {
    set pinPath [::capFind::normalizeLocateArg $pinPath]
    ::capFind::cleanupLastPage
    if {[string first . $pinPath] < 0} {
        puts {capFind: Pin path must be Ref.Pin e.g. U1000.J12}
        return
    }
    if {[::capFind::findPinsCmdSmart $pinPath]} {
        return
    }
    puts "capFind: FindPins failed: $pinPath (and U1000[A-Z].… variants if applicable)."
}

# caploc：含点 → 管脚；无点且含下划线 → 先网络后位号；否则先位号后网络（避免 C1241 被 FindNets 误伤）
proc ::capFind::autoFind {input} {
    set in [::capFind::normalizeLocateArg $input]
    if {[string first . $in] >= 0} {
        ::capFind::locateByPin $in
        return
    }
    ::capFind::cleanupLastPage
    if {[string first _ $in] >= 0} {
        if {[::capFind::findNetsCmd $in]} {
            return
        }
        if {[::capFind::findPartsCmd $in]} {
            return
        }
    } else {
        if {[::capFind::findPartsCmd $in]} {
            return
        }
        if {[::capFind::findNetsCmd $in]} {
            return
        }
    }
    puts "capFind: No match (FindParts / FindNets): $in"
}

proc ::capFind::cleanup {} {
    ::capFind::cleanupLastPage
    foreach pmTab [list {Project Manager} "\u9879\u76ee\u7ba1\u7406\u5668"] {
        catch {SwitchTab $pmTab}
    }
}

proc ::capFind::caplocv {} {
    if {[info script] ne ""} {
        puts [file normalize [info script]]
    }
}

namespace export autoFind locateByRefDes locateByNet locateByPin cleanup caplocv

proc ::capFind::_registerGlobalAliases {} {
    foreach {alias target} {
        caploc  ::capFind::autoFind
        caplocr ::capFind::locateByRefDes
        caplocn ::capFind::locateByNet
        caplocp ::capFind::locateByPin
        caplcc  ::capFind::cleanup
        caplocv ::capFind::caplocv
    } {
        if {[info commands $alias] ne ""} {
            catch {rename $alias ""}
        }
        interp alias {} $alias {} $target
    }
}
::capFind::_registerGlobalAliases
