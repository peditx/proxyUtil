#!/usr/bin/env python3
import argparse
from modules.myUtil import *


def main():
    parser = argparse.ArgumentParser(description="shadowsocks URI to ss-local command")
    parser.add_argument("-i", "--input", help="shadowsocks URI")
    parser.add_argument("-f", "--file", help="file contain shadowsocks URIs")
    parser.add_argument("-o", "--output", help="ss-local command(s) output file")
    parser.add_argument("-l", "--lport", help="local port, default is 1080", default=1080, type=int)
    args = parser.parse_args()
    
    results = []
    
    if args.input :
        results.append( ssURI2sslocal(args.input, args.lport) )
    
    if args.file :
        with open(args.file, 'r') as file:
            lines = parseContent(file.read().strip(), [ss_scheme])
            for line in lines:
                results.append( ssURI2sslocal(line.rstrip(), args.lport) )
    
    outputs = '\n'.join(results) 
    if args.output :
        with open(args.output, 'w') as f :
            f.write(outputs)
    else :
        print(outputs)


if __name__ == '__main__':
    main()
